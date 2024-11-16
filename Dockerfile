def get_container_stats(container):
    """Get CPU, memory usage and other stats for a container"""
    try:
        stats = container.stats(stream=False)  # Get a single stats reading
        
        # Calculate CPU percentage - handling different Docker versions/platforms
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

        # Calculate memory percentage - handling different Docker versions/platforms
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

def get_container_uptime(container):
    """Calculate container uptime in HH:MM:SS format"""
    try:
        started_at = datetime.strptime(container.attrs["State"]["StartedAt"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
        uptime = datetime.utcnow() - started_at
        return str(datetime.utcfromtimestamp(uptime.total_seconds()).strftime('%H:%M:%S'))
    except Exception as e:
        LOGGER.error("Error calculating uptime: %s", e)
        return "00:00:00"

async def process_container(container, hostname, current_container_id):
    LOGGER.debug("Processing container %s", container.name)

    response = None

    if current_container_id and container.id.startswith(current_container_id):
        LOGGER.debug("Skipping (current) container %s", container.name)
        return None  # Skip the current container

    # Get container metrics
    stats = get_container_stats(container)
    uptime = get_container_uptime(container)
    
    try:
        health_status = container.attrs["State"].get("Health", {}).get("Status", "N/A")
        container_status = container.attrs["State"]["Status"]
    except Exception as e:
        LOGGER.error("Error getting container status: %s", e)
        health_status = "N/A"
        container_status = "unknown"

    ports = []
    try:
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
    except Exception as e:
        LOGGER.error("Error processing ports: %s", e)

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