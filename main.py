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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }
        
        .main {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        h1 {
            margin: 0;
            padding: 0;
            font-size: 24px;
        }
        
        h5 {
            margin: 5px 0 20px 0;
            color: #666;
            font-style: italic;
        }
        
        .grid-container {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1fr 1fr 1fr 1fr;
            gap: 1px;
            background-color: #eee;
            border: 1px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .header-cell {
            background-color: #f8f9fa;
            padding: 12px 15px;
            font-weight: 500;
            color: #333;
            font-size: 0.9em;
            text-align: left;
        }
        
        .grid-cell {
            background-color: white;
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }
        
        .container-name {
            font-weight: 500;
        }
        
        .numeric {
            font-family: monospace;
            text-align: right;
        }
        
        .status-cell {
            text-transform: capitalize;
        }
        
        .health-healthy {
            color: #22c55e;
        }
        
        .health-unhealthy {
            color: #ef4444;
        }
        
        .health-starting {
            color: #f59e0b;
        }
        
        .loading {
            opacity: 0.5;
        }
        
        .footer {
            margin-top: 20px;
            text-align: center;
            font-size: 12px;
            color: #666;
            padding: 20px;
        }
        
        .footer a {
            color: #666;
            text-decoration: none;
            margin: 0 10px;
        }
        
        @media (max-width: 768px) {
            .grid-container {
                grid-template-columns: 1fr;
            }
            
            .header-cell:not(:first-child),
            .grid-cell:not(:first-child) {
                display: none;
            }
        }
    </style>
    <script>
        class ContainerMonitor {
            constructor() {
                this.containers = new Map();
                this.updateInterval = 10000;
                this.containerElement = null;
                this.initialized = false;
                this.preloadData();
            }
            
            async preloadData() {
                // Start loading data before DOM is ready
                try {
                    const containers = await this.fetchContainerList();
                    this.containers = new Map(containers.map(c => [c.id, {
                        ...c,
                        cpu_percent: 0,
                        memory_percent: 0,
                        ports: [],
                        uptime: '00:00:00'
                    }]));
                    
                    // Start fetching stats in parallel
                    await this.updateAllContainerStats();
                    
                    if (this.initialized) {
                        this.renderContainers();
                    }
                } catch (error) {
                    console.error('Error preloading data:', error);
                }
            }
            
            async initialize() {
                this.containerElement = document.getElementById('container-data');
                this.initialized = true;
                
                if (this.containers.size > 0) {
                    this.renderContainers();
                }
                
                this.startPeriodicUpdates();
            }
            
            async fetchContainerList() {
                const response = await fetch('/api/containers/list');
                return await response.json();
            }
            
            async updateAllContainerStats() {
                const promises = Array.from(this.containers.keys()).map(id => 
                    this.fetchContainerStats(id)
                );
                
                try {
                    const results = await Promise.allSettled(promises);
                    results.forEach((result, index) => {
                        if (result.status === 'fulfilled') {
                            const containerId = Array.from(this.containers.keys())[index];
                            const container = this.containers.get(containerId);
                            if (container) {
                                Object.assign(container, result.value);
                            }
                        }
                    });
                    
                    if (this.initialized) {
                        this.renderContainers();
                    }
                } catch (error) {
                    console.error('Error updating container stats:', error);
                }
            }
            
            async fetchContainerStats(containerId) {
                const response = await fetch(`/api/containers/${containerId}/stats`);
                return await response.json();
            }
            
            async updateContainerList() {
                try {
                    const containers = await this.fetchContainerList();
                    const currentIds = new Set(containers.map(c => c.id));
                    
                    // Remove old containers
                    for (const [id] of this.containers) {
                        if (!currentIds.has(id)) {
                            this.containers.delete(id);
                        }
                    }
                    
                    // Add new containers
                    for (const container of containers) {
                        if (!this.containers.has(container.id)) {
                            this.containers.set(container.id, {
                                ...container,
                                cpu_percent: 0,
                                memory_percent: 0,
                                ports: [],
                                uptime: '00:00:00'
                            });
                        } else {
                            const existing = this.containers.get(container.id);
                            existing.status = container.status;
                            existing.health = container.health;
                        }
                    }
                    
                    await this.updateAllContainerStats();
                    this.renderContainers();
                } catch (error) {
                    console.error('Error updating container list:', error);
                }
            }
            
            renderContainers() {
                if (!this.containerElement) return;
                
                const containers = [...this.containers.values()]
                    .sort((a, b) => a.name.localeCompare(b.name));
                
                this.containerElement.innerHTML = containers.map(container => {
                    const healthClass = container.health.toLowerCase() !== 'n/a' 
                        ? `health-${container.health.toLowerCase()}` 
                        : '';
                    
                    return `
                        <div class="grid-cell container-name">${container.name}</div>
                        <div class="grid-cell numeric">${container.cpu_percent.toFixed(1)}%</div>
                        <div class="grid-cell numeric">${container.memory_percent.toFixed(1)}%</div>
                        <div class="grid-cell status-cell">${container.status}</div>
                        <div class="grid-cell ${healthClass}">${container.health}</div>
                        <div class="grid-cell">${container.ports.join(', ') || '-'}</div>
                        <div class="grid-cell">${container.uptime}</div>
                    `;
                }).join('');
            }
            
            startPeriodicUpdates() {
                setInterval(() => this.updateContainerList(), this.updateInterval);
            }
        }
        
        // Start preloading data immediately
        const monitor = new ContainerMonitor();
        
        // Initialize UI when DOM is ready
        document.addEventListener('DOMContentLoaded', () => {
            monitor.initialize();
        });
    </script>
</head>
<body>
    <div class="main">
        <h1>What's Running</h1>
        <h5>enhanced</h5>
        
        <div class="grid-container">
            <div class="header-cell">Nome container</div>
            <div class="header-cell">CPU (%)</div>
            <div class="header-cell">Memoria (%)</div>
            <div class="header-cell">Stato</div>
            <div class="header-cell">Health</div>
            <div class="header-cell">Porte</div>
            <div class="header-cell">Creato da</div>
            
            <div id="container-data"></div>
        </div>
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