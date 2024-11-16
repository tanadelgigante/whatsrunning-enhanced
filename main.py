# pylint: disable=missing-module-docstring,missing-function-docstring
import os
import logging
import asyncio
import aiohttp
from datetime import datetime
import docker
from flask import Flask, render_template_string, request
from concurrent.futures import ThreadPoolExecutor

if os.getenv("VERBOSE"):
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# Create a thread pool for Docker operations
DOCKER_POOL = ThreadPoolExecutor(max_workers=4)

CLIENT = docker.DockerClient(
    base_url=os.getenv("DOCKER_HOST", "unix://var/run/docker.sock")
)

CURRENT_CONTAINER_ID = os.getenv("HOSTNAME")
HOSTNAME = os.getenv("HOST_HOSTNAME")
VERSION = os.getenv("VERSION", "unknown")

LOGGER.info(
    "Running as container ID: %s on external host %s",
    CURRENT_CONTAINER_ID,
    HOSTNAME,
)

app = Flask(__name__)

async def get_container_stats(container):
    """Get CPU, memory usage and other stats for a container asynchronously"""
    try:
        # Run stats collection in thread pool to avoid blocking
        stats = await asyncio.get_event_loop().run_in_executor(
            DOCKER_POOL, lambda: container.stats(stream=False)
        )
        
        # Calculate CPU percentage
        cpu_percent = 0.0
        try:
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                         stats["precpu_stats"]["system_cpu_usage"]
            online_cpus = stats["cpu_stats"].get("online_cpus", 
                                                len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])))
            
            if system_delta > 0 and online_cpus > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0 * online_cpus
        except (KeyError, TypeError, ZeroDivisionError) as e:
            LOGGER.warning("Error calculating CPU stats: %s", e)

        # Calculate memory percentage
        memory_percent = 0.0
        try:
            if "memory_stats" in stats:
                memory_usage = stats["memory_stats"].get("usage", 0)
                if "cache" in stats["memory_stats"]:
                    memory_usage = memory_usage - stats["memory_stats"].get("cache", 0)
                memory_limit = stats["memory_stats"].get("limit", 1)
                if memory_limit > 0:
                    memory_percent = (memory_usage / memory_limit) * 100.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            LOGGER.warning("Error calculating memory stats: %s", e)

        return {
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(memory_percent, 2)
        }
    except Exception as e:
        LOGGER.error("Error getting container stats: %s", e)
        return {
            "cpu_percent": 0.0,
            "memory_percent": 0.0
        }

async def get_container_uptime(container):
    """Calculate container uptime in HH:MM:SS format asynchronously"""
    try:
        # Run attribute retrieval in thread pool
        attrs = await asyncio.get_event_loop().run_in_executor(
            DOCKER_POOL, lambda: container.attrs
        )
        started_at = datetime.strptime(attrs["State"]["StartedAt"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
        uptime = datetime.utcnow() - started_at
        return str(datetime.utcfromtimestamp(uptime.total_seconds()).strftime('%H:%M:%S'))
    except Exception as e:
        LOGGER.error("Error calculating uptime: %s", e)
        return "00:00:00"

async def check_port_protocol(hostname, port, timeout=2):
    """Check if a port responds to HTTP/HTTPS with timeout"""
    async with aiohttp.ClientSession() as session:
        for protocol in ["http", "https"]:
            url = f"{protocol}://{hostname}:{port}"
            headers = {"x-whatsrunning-probe": "true"}
            try:
                async with session.get(
                    url, allow_redirects=False, headers=headers, timeout=timeout
                ) as response:
                    LOGGER.debug("url %s returned %s", url, response.status)
                    return protocol
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue
    return None

async def process_container(container, hostname, current_container_id):
    """Process a single container asynchronously"""
    LOGGER.debug("Processing container %s", container.name)

    if current_container_id and container.id.startswith(current_container_id):
        LOGGER.debug("Skipping (current) container %s", container.name)
        return None

    # Get container metrics concurrently
    stats, uptime = await asyncio.gather(
        get_container_stats(container),
        get_container_uptime(container)
    )

    # Get container attributes
    try:
        attrs = await asyncio.get_event_loop().run_in_executor(
            DOCKER_POOL, lambda: container.attrs
        )
        health_status = attrs["State"].get("Health", {}).get("Status", "N/A")
        container_status = attrs["State"]["Status"]
    except Exception as e:
        LOGGER.error("Error getting container status: %s", e)
        health_status = "N/A"
        container_status = "unknown"

    # Process ports
    ports = []
    try:
        if attrs["NetworkSettings"]["Ports"]:
            port_tasks = []
            for name, value in attrs["NetworkSettings"]["Ports"].items():
                if not name.endswith("/tcp") or not value:
                    continue
                candidate_ports = {v["HostPort"] for v in value if "HostPort" in v}
                port_tasks.extend([
                    check_port_protocol(hostname, port) for port in candidate_ports
                ])

            if port_tasks:
                protocols = await asyncio.gather(*port_tasks)
                for port, protocol in zip(candidate_ports, protocols):
                    if protocol and protocol in ["http", "https"]:
                        ports.append((protocol, port))
    except Exception as e:
        LOGGER.error("Error processing ports for %s: %s", container.name, e)

    return {
        "name": container.name,
        "ports": ports,
        "cpu_percent": stats["cpu_percent"],
        "memory_percent": stats["memory_percent"],
        "status": container_status,
        "health": health_status,
        "uptime": uptime
    }

async def process_containers(containers, hostname, current_container_id):
    """Process all containers concurrently with timeout"""
    tasks = [
        asyncio.create_task(process_container(container, hostname, current_container_id))
        for container in sorted(containers, key=lambda c: c.name)
    ]
    
    # Wait for all tasks with timeout
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=25)
        return [result for result in results if result]
    except asyncio.TimeoutError:
        LOGGER.error("Container processing timed out")
        return []

@app.route("/about")
def about():
    return f"Version: {VERSION}"

@app.route("/")
async def list_ports():
    if request.headers.get("x-whatsrunning-probe"):
        LOGGER.debug("Ignoring probe request")
        return "Alive"

    try:
        # Get container list in thread pool
        containers = await asyncio.get_event_loop().run_in_executor(
            DOCKER_POOL, CLIENT.containers.list
        )
    except Exception as e:
        LOGGER.error("Error listing containers: %s", e)
        containers = []

    container_data = await process_containers(containers, HOSTNAME, CURRENT_CONTAINER_ID)

    return render_template_string(
        HTML_TEMPLATE,  # Move the template to a constant at the top of the file
        containers=container_data,
        hostname=HOSTNAME,
        app_version=VERSION,
    )

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("FLASK_PORT", "5000")),
        asyncio_mode="auto"  # Enable async support
    )