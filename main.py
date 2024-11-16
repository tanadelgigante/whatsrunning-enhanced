import os
import logging
import asyncio
from datetime import datetime
import docker
from flask import Flask, render_template_string, request, jsonify

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

app = Flask(__name__)

def get_container_stats(container):
    """Get CPU, memory usage and other stats for a container"""
    try:
        stats = container.stats(stream=False)
        
        # Calculate CPU percentage - with fallback for different Docker versions
        cpu_percent = 0.0
        try:
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                         stats["precpu_stats"]["system_cpu_usage"]
            
            # Get number of CPUs - fallback to 1 if not available
            if "online_cpus" in stats["cpu_stats"]:
                online_cpus = stats["cpu_stats"]["online_cpus"]
            else:
                # Try to get from cpu_usage if available, otherwise default to 1
                online_cpus = 1
                cpu_usage = stats["cpu_stats"]["cpu_usage"]
                if "percpu_usage" in cpu_usage and cpu_usage["percpu_usage"]:
                    online_cpus = len(cpu_usage["percpu_usage"])
            
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

def get_container_uptime(container):
    """Calculate container uptime in HH:MM:SS format"""
    try:
        started_at = datetime.strptime(container.attrs["State"]["StartedAt"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
        uptime = datetime.utcnow() - started_at
        return str(datetime.utcfromtimestamp(uptime.total_seconds()).strftime('%H:%M:%S'))
    except Exception as e:
        LOGGER.error("Error calculating uptime: %s", e)
        return "00:00:00"

@app.route("/api/containers/list")
def list_containers():
    """API endpoint to get basic container information"""
    try:
        containers = CLIENT.containers.list()
        container_data = []
        
        for container in sorted(containers, key=lambda c: c.name):
            if CURRENT_CONTAINER_ID and container.id.startswith(CURRENT_CONTAINER_ID):
                continue
                
            try:
                health_status = container.attrs["State"].get("Health", {}).get("Status", "N/A")
                container_status = container.attrs["State"]["Status"]
            except Exception:
                health_status = "N/A"
                container_status = "unknown"
            
            container_data.append({
                "id": container.id,
                "name": container.name,
                "status": container_status,
                "health": health_status
            })
            
        return jsonify(container_data)
    except Exception as e:
        LOGGER.error("Error listing containers: %s", e)
        return jsonify([])

@app.route("/api/containers/<container_id>/stats")
def get_container_details(container_id):
    """API endpoint to get detailed stats for a single container"""
    try:
        container = CLIENT.containers.get(container_id)
        
        stats = get_container_stats(container)
        uptime = get_container_uptime(container)
        
        ports = []
        try:
            if container.attrs["NetworkSettings"]["Ports"]:
                for name, value in container.attrs["NetworkSettings"]["Ports"].items():
                    if name.endswith("/tcp") and value:
                        ports.extend([v["HostPort"] for v in value if "HostPort" in v])
        except Exception as e:
            LOGGER.error("Error processing ports: %s", e)
        
        return jsonify({
            "cpu_percent": stats["cpu_percent"],
            "memory_percent": stats["memory_percent"],
            "ports": ports,
            "uptime": uptime
        })
    except Exception as e:
        LOGGER.error(f"Error getting container {container_id} stats: {e}")
        return jsonify({
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "ports": [],
            "uptime": "00:00:00"
        })

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>What's Running</title>
    <meta content="text/html; charset=ISO-8859-1" http-equiv="content-type">
    <style>
        .main {
            background-color: black;
            max-width: 800px;
            min-height: 500px;
            font-family: sans-serif;
            margin-right: 25%;
            margin-left: 25%;
            color: #ffcc00;
        }
        h1, h5 {
            text-align: center;
            text-transform: uppercase;
            font-variant: small-caps;
            margin: 0;
        }
        h5 {
            margin-top: 5px;
            margin-bottom: 20px;
        }
        .menu-side, .menu-center-1, .menu-center-2, .menu-center-3, .menu-center-4, .menu-center-5, .menu-center-6 {
            font-weight: bold;
        }
        .menu-side {
            margin-left: 5pt;
            width: 150pt;
            max-width: 30%;
        }
        .menu-center-1 {
            margin-left: 120pt;
        }
        .menu-center-2 {
            margin-left: 170pt;
            padding-left: 15pt;
        }
        .menu-center-3 {
            margin-left: 250pt;
            padding-left: 15pt;
            border-bottom-width: medium;
        }
        .menu-center-4 {
            margin-left: 320pt;
            padding-left: 15pt;
            border-bottom-width: medium;
        }
        .menu-center-5 {
            margin-left: 400pt;
            padding-left: 15pt;
            border-bottom-width: medium;
        }
        .menu-center-6 {
            margin-left: 480pt;
            padding-left: 15pt;
            border-bottom-width: medium;
        }
        .menu {
            border-bottom: thin solid #ffcc00;
            margin-top: 5px;
            position: relative;
            top: -12px;
        }
        .footer {
            border-top: thin solid #ffcc00;
            margin-top: 12%;
            text-align: left;
            padding-top: 10px;
        }
        a {
            color: #cc9933;
            text-decoration: underline;
        }
        .data-row {
            display: flex;
            justify-content: space-between;
            margin: 5px 0;
        }
        .data-row div {
            flex-basis: 100px;
            text-align: left;
        }
    </style>
</head>
<body>
    <div class="main">
        <h1>What's Running</h1>
        <h5>enhanced</h5>
        <div class="menu-side">Nome container</div>
        <div class="menu-center-1">CPU (%)</div>
        <div class="menu-center-2">Memoria (%)</div>
        <div class="menu-center-3">Stato</div>
        <div class="menu-center-4">Health</div>
        <div class="menu-center-5">Porte</div>
        <div class="menu-center-6">Creato da</div>
        <div class="menu">&nbsp;</div>
        <div id="container-data"></div>
        <div class="footer">
            © 2024 Mikeage / Il Gigante<br>
            <a href="#">Github Mikeage</a><br>
            <a href="#">Github Tanadelgigante</a>
        </div>
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', () => {
            // JavaScript per il caricamento dinamico dei container
        });
    </script>
</body>
</html>
"""


@app.route("/")
def list_ports():
    if request.headers.get("x-whatsrunning-probe"):
        return "Alive"
    return render_template_string(HTML_TEMPLATE)

@app.route("/about")
def about():
    return f"Version: {VERSION}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("FLASK_PORT", "5000")))