# Cursor Remote Agent - Multi-Microservice Edition

Control your entire microservices architecture and React frontend from your iPhone. A web-based remote control server that runs on your Mac and provides a mobile-friendly interface for managing multiple Spring Boot services and frontend applications.

## Features

### Multi-Service Management
- **Auto-Detection** - Automatically discovers Spring Boot microservices and React/Vue/Next.js frontends
- **Service Dashboard** - Real-time status of all services with running/stopped indicators
- **Individual Control** - Start, stop, restart, and build each service independently
- **Bulk Operations** - Start or stop all services with one tap
- **Profile Support** - Launch services with different Spring profiles (dev, local, etc.)

### Mobile-Optimized Interface
- **iPhone-First Design** - Beautiful, responsive UI optimized for mobile
- **Quick Actions** - One-tap buttons for common operations
- **Live Statistics** - See running service count at a glance
- **Service Logs** - View real-time logs from any service

### Development Tools
- **Terminal Access** - Execute shell commands in any service directory
- **File Browser** - Browse, view, and edit files across all projects
- **Git Integration** - Check repository status
- **Docker Status** - View running Docker containers

## Quick Start

### 1. Install Dependencies

```bash
cd cursor-remote-agent
pip3 install -r requirements.txt
```

### 2. Start the Server

Point it to your workspace containing all microservices:

```bash
python3 server.py --workspace /path/to/your/workspace --password your-secure-password
```

The server will automatically scan and detect:
- Spring Boot projects (Maven or Gradle)
- React/Next.js/Vue frontends
- Port configurations from application.properties/yml

### 3. Connect from iPhone

1. Ensure your iPhone and Mac are on the same WiFi
2. Find your Mac's IP: `ifconfig | grep "inet "`
3. Open Safari: `http://YOUR_MAC_IP:8765`
4. Enter your password

## Project Structure Example

The agent works great with a typical microservices structure:

```
workspace/
├── user-service/           # Spring Boot microservice (port 8081)
│   ├── pom.xml
│   └── src/
├── order-service/          # Spring Boot microservice (port 8082)
│   ├── pom.xml
│   └── src/
├── payment-service/        # Spring Boot microservice (port 8083)
│   ├── build.gradle
│   └── src/
├── api-gateway/            # Spring Boot gateway (port 8080)
│   ├── pom.xml
│   └── src/
└── frontend/               # React frontend (port 3000)
    ├── package.json
    └── src/
```

## Configuration

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--workspace` | Home directory | Root path containing all projects |
| `--password` | cursor123 | Authentication password |
| `--port` | 8765 | Server port |
| `--host` | 0.0.0.0 | Bind address |

### Environment Variables

```bash
export WORKSPACE_PATH=/path/to/workspace
export AGENT_PASSWORD=mysecurepassword
export AGENT_PORT=8765
python3 server.py
```

### Custom Service Configuration (Optional)

Create `services.json` in your workspace root for manual configuration:

```json
{
  "microservices": [
    {
      "name": "user-service",
      "path": "/path/to/user-service",
      "type": "spring-boot",
      "build_tool": "maven",
      "port": 8081,
      "start_command": "./mvnw spring-boot:run",
      "build_command": "./mvnw clean package -DskipTests"
    }
  ],
  "frontends": [
    {
      "name": "web-app",
      "path": "/path/to/frontend",
      "type": "react",
      "port": 3000,
      "start_command": "npm run dev",
      "build_command": "npm run build",
      "install_command": "npm install"
    }
  ]
}
```

## Mobile Interface Guide

### Dashboard Tab
- **Stats Row** - Shows running services, total microservices, and frontends count
- **Profile Selector** - Choose Spring profile before starting services
- **Quick Actions** - Start All, Stop All, Open Cursor, Refresh
- **Microservices List** - Each service with status and control buttons
- **Frontends List** - React/Vue apps with their controls

### Logs Tab
- Select any running service to view its live output
- Auto-refreshes every 5 seconds
- Useful for debugging startup issues

### Terminal Tab
- Execute commands in any service directory
- Dropdown to select working directory
- Full command output with scrolling

### Files Tab
- Browse any service's files
- Quick navigation dropdown
- Tap to edit files with built-in editor

## API Reference

### Service Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/services` | GET | List all configured services |
| `/api/services/status` | GET | Get status of all services |
| `/api/services/refresh` | POST | Re-detect services |
| `/api/services/start-all` | POST | Start all services |
| `/api/services/stop-all` | POST | Stop all services |

### Individual Service Control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/service/{name}/start` | POST | Start a service |
| `/api/service/{name}/stop` | POST | Stop a service |
| `/api/service/{name}/restart` | POST | Restart a service |
| `/api/service/{name}/build` | POST | Build a service |
| `/api/service/{name}/output` | GET | Get service logs |

### Utility Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/execute` | POST | Execute shell command |
| `/api/files/list` | GET | List directory |
| `/api/files/read` | GET | Read file |
| `/api/files/write` | POST | Write file |
| `/api/docker/status` | GET | Docker container status |

## Running as Background Service

### Using nohup

```bash
nohup python3 server.py --workspace /path/to/workspace --password mypassword > agent.log 2>&1 &
```

### Using launchd (macOS)

Create `~/Library/LaunchAgents/com.cursor.remote-agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cursor.remote-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/cursor-remote-agent/server.py</string>
        <string>--workspace</string>
        <string>/path/to/your/workspace</string>
        <string>--password</string>
        <string>your-password</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.cursor.remote-agent.plist
```

## Troubleshooting

### Services not detected

1. Check that `pom.xml` or `build.gradle` contains spring-boot dependencies
2. Ensure `package.json` has react/vue/next in dependencies
3. Try the "Re-detect Services" button in Settings

### Service won't start

1. Check if the port is already in use: `lsof -i :PORT`
2. Ensure build wrapper is executable: `chmod +x mvnw` or `chmod +x gradlew`
3. View service logs for errors

### Can't connect from iPhone

1. Both devices must be on the same WiFi network
2. Check Mac firewall settings
3. Verify server is running: `lsof -i :8765`

### Port Detection Issues

The agent looks for ports in:
- `application.properties`: `server.port=8081`
- `application.yml`: `server: port: 8081`
- Frontend `.env` files: `PORT=3000`

## Security Notes

- Only accessible on local network by default
- All endpoints require authentication
- Sessions expire after 1 hour of inactivity
- Consider using HTTPS in production environments

## License

MIT License - Use freely for personal and commercial projects.
