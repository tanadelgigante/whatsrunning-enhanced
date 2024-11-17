# What's Running Enhanced

A fork of [mikeage's What's Running](https://github.com/mikeage/whatsrunning) with enhanced features for monitoring Docker containers. This web application provides a real-time dashboard to monitor Docker containers running on your system, displaying detailed statistics including CPU usage, memory consumption, health status, and uptime.

## Features

- Real-time monitoring of Docker containers
- Detailed container statistics:
  - CPU usage percentage
  - Memory usage percentage
  - Container status and health
  - Exposed ports
  - Container uptime
- Automatic refresh every 10 seconds
- Responsive design for both desktop and mobile devices
- Dark theme interface
- Multi-architecture support (x86_64, aarch64, armv7l, armv6)

## Requirements

- Docker
- Python 3.12 (for local development)
- Docker socket access

## Installation

### Using Docker

```bash
docker pull tanadelgigante/whatsrunning-enhanced:latest
```

Run the container:

```bash
docker run -d \
  -p 5000:5000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  tanadelgigante/whatsrunning-enhanced:latest
```

### Building from Source

1. Clone the repository:
```bash
git clone https://github.com/tanadelgigante/whatsrunning-enhanced.git
cd whatsrunning-enhanced
```

2. Build the Docker image:
```bash
docker build -t whatsrunning-enhanced .
```

For ARMv6 devices (like Raspberry Pi Zero):
```bash
docker build -f Dockerfile.armv6 -t whatsrunning-enhanced .
```

## Environment Variables

- `DOCKER_HOST`: Docker daemon socket (default: "unix://var/run/docker.sock")
- `FLASK_PORT`: Port to run the application on (default: 5000)
- `VERBOSE`: Enable verbose logging (set to any value to enable)
- `VERSION`: Application version (set during build)

## Usage

After starting the container, access the dashboard at:

```
http://localhost:5000
```

## Development

Requirements:
- Python 3.12
- Flask
- Docker SDK for Python
- aiohttp
- gunicorn

Install dependencies:
```bash
pip install flask docker aiohttp gunicorn
```

Run locally:
```bash
python main.py
```

## Differences from Original

This enhanced version includes:
- Multi-architecture support (including ARMv6)
- Improved UI with dark theme
- Real-time statistics updates
- Container health monitoring
- Uptime tracking
- Enhanced error handling
- Responsive design improvements

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Original project by [mikeage](https://github.com/mikeage/whatsrunning)

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Disclaimer

The original project does not have an explicit license. This fork is released under GPL-3, applying only to the modifications and enhancements made to the original code.