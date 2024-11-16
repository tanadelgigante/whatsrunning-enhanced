# pylint: disable=missing-module-docstring,missing-function-docstring
import os
import logging
import asyncio
import aiohttp
import datetime
from datetime import datetime

import docker
from flask import Flask, render_template_string, request

if os.getenv("VERBOSE"):
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

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

def get_container_stats(container):
    """Get CPU, memory usage and other stats for a container"""
    stats = container.stats(stream=False)  # Get a single stats reading
    
    # Calculate CPU percentage
    cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                stats["precpu_stats"]["cpu_usage"]["total_usage"]
    system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                  stats["precpu_stats"]["system_cpu_usage"]
    cpu_percent = 0.0
    if system_delta > 0:
        cpu_percent = (cpu_delta / system_delta) * len(stats["cpu_stats"]["cpu_usage"]["percpu_usage"]) * 100.0

    # Calculate memory percentage
    memory_usage = stats["memory_stats"]["usage"]
    memory_limit = stats["memory_stats"]["limit"]
    memory_percent = (memory_usage / memory_limit) * 100.0

    return {
        "cpu_percent": round(cpu_percent, 2),
        "memory_percent": round(memory_percent, 2)
    }

def get_container_uptime(container):
    """Calculate container uptime in HH:MM:SS format"""
    started_at = datetime.strptime(container.attrs["State"]["StartedAt"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
    uptime = datetime.utcnow() - started_at
    return str(datetime.utcfromtimestamp(uptime.total_seconds()).strftime('%H:%M:%S'))

async def check_port_protocol(hostname, port):
    async with aiohttp.ClientSession() as session:
        for protocol in ["http", "https"]:
            url = f"{protocol}://{hostname}:{port}"
            headers = {"x-whatsrunning-probe": "true"}
            try:
                async with session.get(
                    url, allow_redirects=False, headers=headers, timeout=2
                ) as response:
                    LOGGER.debug("url %s returned %s", url, response.status)
                    return protocol
            except aiohttp.ClientError:
                pass
            except asyncio.TimeoutError:
                LOGGER.warning("Timeout waiting for %s", url)

    return None

async def process_container(container, hostname, current_container_id):
    LOGGER.debug("Processing container %s", container.name)

    response = None

    if current_container_id and container.id.startswith(current_container_id):
        LOGGER.debug("Skipping (current) container %s", container.name)
        return None  # Skip the current container

    # Get container metrics
    stats = get_container_stats(container)
    uptime = get_container_uptime(container)
    health_status = container.attrs["State"].get("Health", {}).get("Status", "N/A")
    container_status = container.attrs["State"]["Status"]

    ports = []
    if container.attrs["NetworkSettings"]["Ports"]:
        for name, value in container.attrs["NetworkSettings"]["Ports"].items():
            if not name.endswith("/tcp"):
                continue
            if not value:
                continue
            candidate_ports = {v["HostPort"] for v in value if "HostPort" in v}

            LOGGER.debug(
                "Container %s has published ports %s", container.name, candidate_ports
            )

            check_protocol_tasks = [
                check_port_protocol(hostname, port) for port in candidate_ports
            ]
            protocols = await asyncio.gather(*check_protocol_tasks)

            for port, protocol in zip(candidate_ports, protocols):
                if protocol and protocol in ["http", "https"]:
                    ports.append((protocol, port))

    if ports or not ports:  # Always return container info even if no ports
        response = {
            "name": container.name,
            "ports": ports,
            "cpu_percent": stats["cpu_percent"],
            "memory_percent": stats["memory_percent"],
            "status": container_status,
            "health": health_status,
            "uptime": uptime
        }

    LOGGER.debug("For container %s, found %s", container.name, response)

    return response

async def process_containers(containers, hostname, current_container_id):
    tasks = [
        process_container(container, hostname, current_container_id)
        for container in sorted(containers, key=lambda c: c.name)
    ]

    results = await asyncio.gather(*tasks)
    container_data = [result for result in results if result]

    return container_data

@app.route("/about")
def about():
    return f"Version: {VERSION}"

# Modifica della route principale per includere il nuovo template

@app.route("/")
def list_ports():
    if request.headers.get("x-whatsrunning-probe"):
        LOGGER.debug("Ignoring probe request")
        return "Alive"

    containers = CLIENT.containers.list()

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>What's Running</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }
            
            h1 {
                margin: 0;
                padding: 0;
                font-size: 24px;
            }
            
            h5 {
                margin: 5px 0 20px 0;
                color: #666;
            }
            
            .container {
                position: relative;
                padding-top: 40px; /* Space for header */
            }
            
            .menu-header {
                display: grid;
                grid-template-columns: 150px repeat(6, 1fr);
                gap: 10px;
                margin-bottom: 10px;
                font-weight: bold;
                background-color: #fff;
                padding: 10px;
                border-radius: 5px;
                position: sticky;
                top: 0;
            }
            
            .data-row {
                display: grid;
                grid-template-columns: 150px repeat(6, 1fr);
                gap: 10px;
                padding: 10px;
                background-color: #fff;
                margin-bottom: 5px;
                border-radius: 5px;
                position: relative;
            }
            
            .footer {
                margin-top: 20px;
                text-align: center;
                font-size: 12px;
                color: #666;
            }
            
            .footer a {
                color: #666;
                text-decoration: none;
                margin: 0 10px;
            }
            
            .health-healthy {
                color: green;
            }
            
            .health-unhealthy {
                color: red;
            }
            
            .health-starting {
                color: orange;
            }
        </style>
    </head>
    <body>
        <h1>What's Running</h1>
        <h5>enhanced</h5>
        
        <div class="container">
            <div class="menu-header">
                <div>Nome container</div>
                <div>CPU (%)</div>
                <div>Memoria (%)</div>
                <div>Stato</div>
                <div>Health</div>
                <div>Porte</div>
                <div>Uptime</div>
            </div>
            
            {% for container in containers %}
            <div class="data-row" style="top: {{ loop.index0 * 30 }}px;">
                <div>{{ container.name }}</div>
                <div>{{ container.cpu_percent }}</div>
                <div>{{ container.memory_percent }}</div>
                <div>{{ container.status }}</div>
                <div class="health-{{ container.health.lower() if container.health != 'N/A' else '' }}">
                    {{ container.health }}
                </div>
                <div>
                    {% for (prefix, port) in container.ports %}
                        {{ port }}{% if not loop.last %}, {% endif %}
                    {% endfor %}
                </div>
                <div>{{ container.uptime }}</div>
            </div>
            {% endfor %}
        </div>
        
        <div class="footer">
            © 2024 Mikeage / Il Gigante<br>
            <a href="#">Github Mikeage</a>
            <a href="#">Github Tanadelgigante</a>
        </div>
    </body>
    </html>
    """

    container_data = asyncio.run(
        process_containers(containers, HOSTNAME, CURRENT_CONTAINER_ID)
    )

    return render_template_string(
        html_template,
        containers=container_data,
        hostname=HOSTNAME,
        app_version=VERSION,
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("FLASK_PORT", "5000")))