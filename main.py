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
<html>
<head>
    <title>What's Running</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
          margin: 0;
          padding: 20px;
          font-family: Arial,sans-serif;
          background-color: black;
        }
        h1 {
          margin: 0;
          padding: 0;
          font-size: xx-large;
          text-align: center;
          text-decoration: underline;
          font-weight: bold;
          font-family: Arial,Helvetica,sans-serif;
          text-transform: uppercase;
          color: #ffcc00;
        }
        h5 {
          margin: 5px 0 20px;
          color: #907300;
          font-weight: bold;
          text-transform: uppercase;
          text-align: center;
          font-family: Arial,Helvetica,sans-serif;
        }
        .container {
          position: relative;
          padding-top: 40px;
          background-color: #333333;
        }
        .menu-header {
          padding: 10px;
          margin-bottom: 10px;
          font-weight: bold;
          background-color: #333333;
          top: 0;
          z-index: 1000;
          font-family: Arial,Helvetica,sans-serif;
          color: #ffcc00;
        }
        .data-row {
          padding: 10px;
          background-color: #333333;
          margin-bottom: 5px;
        }
        .data-row:hover {
          background-color: black;
        }
        .footer {
          margin-top: 20px;
          text-align: center;
          font-size: 12px;
          color: #ffcc00;
        }
        .footer a {
          margin: 0 10px;
          color: #ffcc00;
          text-decoration: none;
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
          padding: 5px 10px;
          background: black none repeat scroll 0% 50%;
          position: fixed;
          top: 20px;
          right: 20px;
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
        class ContainerMonitor {
            constructor() {
                this.containers = new Map();
                this.updateInterval = 10000; // 10 seconds
                this.containerElement = document.getElementById('container-data');
            }
            
            async initialize() {
                await this.updateContainerList();
                this.startPeriodicUpdates();
            }
            
            async updateContainerList() {
                try {
                    const response = await fetch('/api/containers/list');
                    const containers = await response.json();
                    
                    // Update container map
                    const currentIds = new Set(containers.map(c => c.id));
                    
                    // Remove containers that no longer exist
                    for (const [id] of this.containers) {
                        if (!currentIds.has(id)) {
                            this.containers.delete(id);
                        }
                    }
                    
                    // Add or update containers
                    for (const container of containers) {
                        if (!this.containers.has(container.id)) {
                            this.containers.set(container.id, {
                                ...container,
                                cpu_percent: 0,
                                memory_percent: 0,
                                ports: [],
                                uptime: '00:00:00'
                            });
                            this.updateContainerStats(container.id);
                        } else {
                            // Update basic info
                            const existing = this.containers.get(container.id);
                            existing.status = container.status;
                            existing.health = container.health;
                        }
                    }
                    
                    this.renderContainers();
                } catch (error) {
                    console.error('Error updating container list:', error);
                }
            }
            
            async updateContainerStats(containerId) {
                try {
                    const response = await fetch(`/api/containers/${containerId}/stats`);
                    const stats = await response.json();
                    
                    const container = this.containers.get(containerId);
                    if (container) {
                        Object.assign(container, stats);
                        this.renderContainers();
                    }
                } catch (error) {
                    console.error(`Error updating stats for container ${containerId}:`, error);
                }
            }
            
            renderContainers() {
                this.containerElement.innerHTML = '';
                
                for (const container of [...this.containers.values()].sort((a, b) => a.name.localeCompare(b.name))) {
                    const row = document.createElement('div');
                    row.className = 'data-row';
                    
                    const healthClass = container.health.toLowerCase() !== 'n/a' 
                        ? `health-${container.health.toLowerCase()}` 
                        : '';
                    
                    row.innerHTML = `
                        <div>${container.name}</div>
                        <div>${container.cpu_percent}%</div>
                        <div>${container.memory_percent}%</div>
                        <div>${container.status}</div>
                        <div class="${healthClass}">${container.health}</div>
                        <div>${container.ports.join(', ')}</div>
                        <div>${container.uptime}</div>
                    `;
                    
                    this.containerElement.appendChild(row);
                }
            }
            
            startPeriodicUpdates() {
                setInterval(() => this.updateContainerList(), this.updateInterval);
                
                // Update stats for each container every 10 seconds, staggered by 1 second each
                setInterval(() => {
                    let delay = 0;
                    for (const [containerId] of this.containers) {
                        setTimeout(() => this.updateContainerStats(containerId), delay);
                        delay += 1000;
                    }
                }, this.updateInterval);
            }
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            const monitor = new ContainerMonitor();
            monitor.initialize();
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
    </div>
    <div class="footer"> © 2024 Mikeage / Il Gigante<br>
        <a href="#">Github Mikeage</a> <a href="#">Github Tanadelgigante</a> 
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