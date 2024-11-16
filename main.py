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

@app.route("/api/containers")
def get_containers():
    """API endpoint to get container data"""
    try:
        containers = CLIENT.containers.list()
        container_data = []
        
        for container in sorted(containers, key=lambda c: c.name):
            if CURRENT_CONTAINER_ID and container.id.startswith(CURRENT_CONTAINER_ID):
                continue
                
            stats = get_container_stats(container)
            uptime = get_container_uptime(container)
            
            try:
                health_status = container.attrs["State"].get("Health", {}).get("Status", "N/A")
                container_status = container.attrs["State"]["Status"]
            except Exception:
                health_status = "N/A"
                container_status = "unknown"
            
            ports = []
            try:
                if container.attrs["NetworkSettings"]["Ports"]:
                    for name, value in container.attrs["NetworkSettings"]["Ports"].items():
                        if name.endswith("/tcp") and value:
                            ports.extend([v["HostPort"] for v in value if "HostPort" in v])
            except Exception as e:
                LOGGER.error("Error processing ports: %s", e)
            
            container_data.append({
                "name": container.name,
                "ports": ports,
                "cpu_percent": stats["cpu_percent"],
                "memory_percent": stats["memory_percent"],
                "status": container_status,
                "health": health_status,
                "uptime": uptime
            })
            
        return jsonify(container_data)
    except Exception as e:
        LOGGER.error("Error processing containers: %s", e)
        return jsonify([])

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>What's Running</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
            padding-top: 40px;
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
            z-index: 1000;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .data-row {
            display: grid;
            grid-template-columns: 150px repeat(6, 1fr);
            gap: 10px;
            padding: 10px;
            background-color: #fff;
            margin-bottom: 5px;
            border-radius: 5px;
            transition: background-color 0.3s ease;
        }
        
        .data-row:hover {
            background-color: #f8f9fa;
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
            color: #28a745;
        }
        
        .health-unhealthy {
            color: #dc3545;
        }
        
        .health-starting {
            color: #ffc107;
        }
        
        .refresh-timer {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #fff;
            padding: 5px 10px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        @media (max-width: 768px) {
            .menu-header, .data-row {
                grid-template-columns: 1fr 1fr;
            }
            
            .menu-header > div, .data-row > div {
                padding: 5px 0;
            }
        }
    </style>
    <script>
        function updateContainers() {
            fetch('/api/containers')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('container-data');
                    container.innerHTML = '';
                    
                    data.forEach(item => {
                        const row = document.createElement('div');
                        row.className = 'data-row';
                        
                        const healthClass = item.health.toLowerCase() !== 'n/a' 
                            ? `health-${item.health.toLowerCase()}` 
                            : '';
                        
                        row.innerHTML = `
                            <div>${item.name}</div>
                            <div>${item.cpu_percent}%</div>
                            <div>${item.memory_percent}%</div>
                            <div>${item.status}</div>
                            <div class="${healthClass}">${item.health}</div>
                            <div>${item.ports.join(', ')}</div>
                            <div>${item.uptime}</div>
                        `;
                        
                        container.appendChild(row);
                    });
                })
                .catch(error => console.error('Error fetching data:', error));
        }
        
        function updateTimer() {
            const timerElement = document.getElementById('refresh-timer');
            let seconds = 10;
            
            function tick() {
                timerElement.textContent = `Refreshing in ${seconds}s`;
                seconds--;
                
                if (seconds < 0) {
                    seconds = 10;
                    updateContainers();
                }
            }
            
            tick();
            setInterval(tick, 1000);
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            updateContainers();
            updateTimer();
        });
    </script>
</head>
<body>
    <h1>What's Running</h1>
    <h5>enhanced</h5>
    
    <div class="refresh-timer" id="refresh-timer">Refreshing in 10s</div>
    
    <div class="container">
        <div class="menu-header">
            <div>Container Name</div>
            <div>CPU (%)</div>
            <div>Memory (%)</div>
            <div>Status</div>
            <div>Health</div>
            <div>Ports</div>
            <div>Uptime</div>
        </div>
        
        <div id="container-data"></div>
    </div>
    
    <div class="footer">
        © 2024 Mikeage / Il Gigante<br>
        <a href="#">Github Mikeage</a>
        <a href="#">Github Tanadelgigante</a>
    </div>
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