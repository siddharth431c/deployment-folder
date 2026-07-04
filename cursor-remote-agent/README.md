# Cursor Remote Agent

Control your Cursor IDE and Spring Boot development from your iPhone. A web-based remote control server that runs on your Mac and provides a mobile-friendly interface for development tasks.

## Features

- **Mobile-Optimized UI** - Beautiful, responsive interface designed for iPhone
- **Terminal Access** - Execute shell commands remotely
- **File Browser** - Browse, view, and edit files on your Mac
- **Spring Boot Integration** - Start, stop, and monitor your Spring Boot application
- **Process Management** - View and control running processes
- **Git Integration** - Check git status and manage your repository
- **Cursor IDE Control** - Open files directly in Cursor

## Quick Start

### 1. Install Dependencies

On your Mac, open Terminal and run:

```bash
cd /path/to/cursor-remote-agent
pip3 install -r requirements.txt
```

Or if you use a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the Server

```bash
python3 server.py --project /path/to/your/spring-boot-project --password your-secure-password
```

**Options:**
- `--project` - Path to your Spring Boot project (default: home directory)
- `--password` - Password for authentication (default: cursor123)
- `--port` - Port to run the server on (default: 8765)
- `--host` - Host to bind to (default: 0.0.0.0)

### 3. Find Your Mac's IP Address

In Terminal, run:

```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

Look for an IP like `192.168.1.xxx` on your local network.

### 4. Connect from Your iPhone

1. Make sure your iPhone is on the same WiFi network as your Mac
2. Open Safari on your iPhone
3. Navigate to: `http://YOUR_MAC_IP:8765`
4. Enter the password you set when starting the server
5. Start developing remotely!

## Usage Guide

### Dashboard

The main dashboard shows:
- **Quick Actions** - One-tap buttons for common tasks
- **Spring Boot Status** - Real-time status of your application
- **Running Processes** - All background processes you've started

### Terminal

Execute any shell command:
- Type commands and tap "Send"
- View real-time output
- Access command history with quick-tap rerun

Common commands:
- `./mvnw clean install` - Build your project
- `./mvnw test` - Run tests
- `git pull` - Pull latest changes
- `tail -f logs/application.log` - View logs

### File Browser

- Navigate your project directory
- Tap folders to enter them
- Tap files to view/edit
- Edit and save files directly from your phone

### Spring Boot Controls

- **Start** - Automatically detects Maven/Gradle and starts your app
- **Stop** - Gracefully stops the running application
- **Status** - Shows if the app is running and on which port

## Environment Variables

You can also configure the server using environment variables:

```bash
export PROJECT_PATH=/path/to/project
export AGENT_PASSWORD=mysecurepassword
export AGENT_PORT=8765
export AGENT_HOST=0.0.0.0

python3 server.py
```

## Running as a Background Service

### Using nohup

```bash
nohup python3 server.py --project /path/to/project --password mypassword > agent.log 2>&1 &
```

### Using launchd (Recommended for Mac)

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
        <string>--project</string>
        <string>/path/to/your/spring-boot-project</string>
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

## Security Considerations

1. **Network Security** - Only accessible on your local network by default
2. **Password Protection** - All endpoints require authentication
3. **Session Management** - Sessions expire after 1 hour of inactivity
4. **HTTPS** - For production use, consider adding SSL/TLS

### Adding HTTPS (Optional)

For secure connections, you can use a reverse proxy like nginx or run with SSL directly.

## Troubleshooting

### Can't connect from iPhone

1. Ensure both devices are on the same WiFi network
2. Check if your Mac's firewall is blocking the port
3. Verify the server is running: `lsof -i :8765`

### Spring Boot won't start

1. Check if `pom.xml` or `build.gradle` exists in the project path
2. Ensure `mvnw` or `gradlew` is executable: `chmod +x mvnw`
3. View the process output for error details

### Commands timeout

- Increase the timeout in the API call
- For long-running commands, use the "Start Process" feature instead

## API Reference

The server exposes a REST API that you can also use programmatically:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Server status |
| `/api/execute` | POST | Execute a command |
| `/api/files/list` | GET | List directory contents |
| `/api/files/read` | GET | Read file contents |
| `/api/files/write` | POST | Write file contents |
| `/api/spring-boot/status` | GET | Spring Boot status |
| `/api/spring-boot/start` | POST | Start Spring Boot |
| `/api/spring-boot/stop` | POST | Stop Spring Boot |
| `/api/git/status` | GET | Git repository status |
| `/api/process/list` | GET | List running processes |
| `/api/cursor/open` | POST | Open file in Cursor |

## License

MIT License - Use freely for personal and commercial projects.
