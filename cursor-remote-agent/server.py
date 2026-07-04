#!/usr/bin/env python3
"""
Cursor Remote Agent - Control your Cursor IDE from your iPhone
A web-based remote control server for multi-microservice development
Supports multiple Spring Boot services + React frontend
"""

import os
import sys
import json
import subprocess
import threading
import time
import secrets
import hashlib
import signal
import re
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, session, 
    redirect, url_for, Response, stream_with_context
)
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app)

# Configuration
CONFIG = {
    'workspace_path': os.environ.get('WORKSPACE_PATH', os.path.expanduser('~')),
    'password': os.environ.get('AGENT_PASSWORD', 'cursor123'),
    'port': int(os.environ.get('AGENT_PORT', 8765)),
    'host': os.environ.get('AGENT_HOST', '0.0.0.0'),
    'session_timeout': 3600,
    'max_output_lines': 500,
    'services_config': None,  # Will be loaded from services.json
}

# Global state for running processes and services
running_processes = {}
managed_services = {}
command_history = []
log_buffer = []


def add_log(level, message):
    """Add a log entry"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'level': level,
        'message': message
    }
    log_buffer.append(entry)
    if len(log_buffer) > 1000:
        log_buffer.pop(0)
    print(f"[{level.upper()}] {message}")


def load_services_config():
    """Load services configuration from file or auto-detect"""
    config_path = os.path.join(CONFIG['workspace_path'], 'services.json')
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                CONFIG['services_config'] = json.load(f)
                add_log('info', f'Loaded services config from {config_path}')
                return
        except Exception as e:
            add_log('warning', f'Failed to load services config: {e}')
    
    # Auto-detect services
    CONFIG['services_config'] = auto_detect_services()


def auto_detect_services():
    """Auto-detect microservices and frontend in workspace"""
    services = {'microservices': [], 'frontends': []}
    workspace = CONFIG['workspace_path']
    
    add_log('info', f'Auto-detecting services in {workspace}')
    
    # Search for Spring Boot projects (pom.xml or build.gradle with spring-boot)
    for root, dirs, files in os.walk(workspace):
        # Skip common non-project directories
        dirs[:] = [d for d in dirs if d not in ['node_modules', 'target', 'build', '.git', 'dist', '.idea', 'venv']]
        
        depth = root.replace(workspace, '').count(os.sep)
        if depth > 3:  # Don't go too deep
            continue
        
        # Check for Spring Boot (Maven)
        if 'pom.xml' in files:
            pom_path = os.path.join(root, 'pom.xml')
            try:
                with open(pom_path, 'r') as f:
                    content = f.read()
                    if 'spring-boot' in content.lower():
                        service_name = os.path.basename(root)
                        # Try to detect port from application.properties/yml
                        port = detect_spring_port(root)
                        services['microservices'].append({
                            'name': service_name,
                            'path': root,
                            'type': 'spring-boot',
                            'build_tool': 'maven',
                            'port': port,
                            'start_command': './mvnw spring-boot:run' if os.path.exists(os.path.join(root, 'mvnw')) else 'mvn spring-boot:run',
                            'build_command': './mvnw clean package -DskipTests' if os.path.exists(os.path.join(root, 'mvnw')) else 'mvn clean package -DskipTests'
                        })
                        add_log('info', f'Detected Spring Boot (Maven): {service_name} on port {port}')
            except Exception as e:
                pass
        
        # Check for Spring Boot (Gradle)
        if 'build.gradle' in files or 'build.gradle.kts' in files:
            gradle_file = 'build.gradle.kts' if 'build.gradle.kts' in files else 'build.gradle'
            gradle_path = os.path.join(root, gradle_file)
            try:
                with open(gradle_path, 'r') as f:
                    content = f.read()
                    if 'spring-boot' in content.lower() or 'org.springframework.boot' in content:
                        service_name = os.path.basename(root)
                        port = detect_spring_port(root)
                        services['microservices'].append({
                            'name': service_name,
                            'path': root,
                            'type': 'spring-boot',
                            'build_tool': 'gradle',
                            'port': port,
                            'start_command': './gradlew bootRun' if os.path.exists(os.path.join(root, 'gradlew')) else 'gradle bootRun',
                            'build_command': './gradlew build -x test' if os.path.exists(os.path.join(root, 'gradlew')) else 'gradle build -x test'
                        })
                        add_log('info', f'Detected Spring Boot (Gradle): {service_name} on port {port}')
            except Exception as e:
                pass
        
        # Check for React/Node.js frontend
        if 'package.json' in files:
            pkg_path = os.path.join(root, 'package.json')
            try:
                with open(pkg_path, 'r') as f:
                    pkg = json.load(f)
                    deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
                    
                    # Detect React
                    if 'react' in deps or 'next' in deps or 'vue' in deps or 'angular' in deps.get('@angular/core', ''):
                        frontend_type = 'react'
                        if 'next' in deps:
                            frontend_type = 'nextjs'
                        elif 'vue' in deps:
                            frontend_type = 'vue'
                        
                        service_name = pkg.get('name', os.path.basename(root))
                        port = detect_frontend_port(root, pkg)
                        
                        # Determine start command
                        scripts = pkg.get('scripts', {})
                        start_cmd = 'npm start'
                        if 'dev' in scripts:
                            start_cmd = 'npm run dev'
                        elif 'start' in scripts:
                            start_cmd = 'npm start'
                        
                        services['frontends'].append({
                            'name': service_name,
                            'path': root,
                            'type': frontend_type,
                            'port': port,
                            'start_command': start_cmd,
                            'build_command': 'npm run build',
                            'install_command': 'npm install'
                        })
                        add_log('info', f'Detected {frontend_type} frontend: {service_name} on port {port}')
            except Exception as e:
                pass
    
    return services


def detect_spring_port(project_path):
    """Detect Spring Boot port from configuration files"""
    # Check application.properties
    props_path = os.path.join(project_path, 'src', 'main', 'resources', 'application.properties')
    if os.path.exists(props_path):
        try:
            with open(props_path, 'r') as f:
                for line in f:
                    if 'server.port' in line:
                        match = re.search(r'server\.port\s*=\s*(\d+)', line)
                        if match:
                            return int(match.group(1))
        except:
            pass
    
    # Check application.yml
    yml_path = os.path.join(project_path, 'src', 'main', 'resources', 'application.yml')
    if os.path.exists(yml_path):
        try:
            with open(yml_path, 'r') as f:
                content = f.read()
                match = re.search(r'port:\s*(\d+)', content)
                if match:
                    return int(match.group(1))
        except:
            pass
    
    # Check application.yaml
    yaml_path = os.path.join(project_path, 'src', 'main', 'resources', 'application.yaml')
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, 'r') as f:
                content = f.read()
                match = re.search(r'port:\s*(\d+)', content)
                if match:
                    return int(match.group(1))
        except:
            pass
    
    return 8080  # Default Spring Boot port


def detect_frontend_port(project_path, package_json):
    """Detect frontend port from configuration"""
    # Check for port in scripts
    scripts = package_json.get('scripts', {})
    for script in scripts.values():
        match = re.search(r'--port[=\s]+(\d+)', str(script))
        if match:
            return int(match.group(1))
        match = re.search(r'-p[=\s]+(\d+)', str(script))
        if match:
            return int(match.group(1))
    
    # Check for .env file
    env_path = os.path.join(project_path, '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    if 'PORT' in line:
                        match = re.search(r'PORT\s*=\s*(\d+)', line)
                        if match:
                            return int(match.group(1))
        except:
            pass
    
    return 3000  # Default React port


def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    """Main dashboard - redirect to login if not authenticated"""
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template('index.html', 
                          workspace_path=CONFIG['workspace_path'],
                          services=CONFIG['services_config'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == CONFIG['password']:
            session['authenticated'] = True
            session['login_time'] = datetime.now().isoformat()
            add_log('info', 'User logged in from ' + request.remote_addr)
            return redirect(url_for('index'))
        add_log('warning', 'Failed login attempt from ' + request.remote_addr)
        return render_template('login.html', error='Invalid password')
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/status')
@require_auth
def api_status():
    """Get server status"""
    return jsonify({
        'status': 'running',
        'workspace_path': CONFIG['workspace_path'],
        'running_processes': len(running_processes),
        'managed_services': len(managed_services),
        'uptime': datetime.now().isoformat()
    })


@app.route('/api/services')
@require_auth
def api_services():
    """Get all configured services"""
    return jsonify(CONFIG['services_config'])


@app.route('/api/services/refresh', methods=['POST'])
@require_auth
def api_services_refresh():
    """Re-detect services"""
    CONFIG['services_config'] = auto_detect_services()
    return jsonify({
        'success': True,
        'services': CONFIG['services_config']
    })


@app.route('/api/services/status')
@require_auth
def api_services_status():
    """Get status of all services"""
    statuses = []
    
    # Check microservices
    for svc in CONFIG['services_config'].get('microservices', []):
        status = check_service_status(svc)
        statuses.append(status)
    
    # Check frontends
    for svc in CONFIG['services_config'].get('frontends', []):
        status = check_service_status(svc)
        statuses.append(status)
    
    return jsonify({'services': statuses})


def check_service_status(service):
    """Check if a service is running"""
    port = service.get('port', 0)
    name = service['name']
    
    # Check if we have a managed process
    if name in managed_services:
        proc_info = managed_services[name]
        proc = proc_info.get('process')
        if proc and proc.poll() is None:
            return {
                **service,
                'status': 'running',
                'managed': True,
                'pid': proc.pid
            }
    
    # Check if port is in use
    if port:
        try:
            result = subprocess.run(
                f"lsof -i :{port} -t",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                return {
                    **service,
                    'status': 'running',
                    'managed': False,
                    'pid': pids[0]
                }
        except:
            pass
    
    return {
        **service,
        'status': 'stopped',
        'managed': False,
        'pid': None
    }


@app.route('/api/service/<service_name>/start', methods=['POST'])
@require_auth
def api_service_start(service_name):
    """Start a specific service"""
    # Find service
    service = None
    for svc in CONFIG['services_config'].get('microservices', []) + CONFIG['services_config'].get('frontends', []):
        if svc['name'] == service_name:
            service = svc
            break
    
    if not service:
        return jsonify({'error': f'Service {service_name} not found'}), 404
    
    # Check if already running
    status = check_service_status(service)
    if status['status'] == 'running':
        return jsonify({'error': f'Service {service_name} is already running'}), 400
    
    # Get optional profile/environment
    data = request.get_json() or {}
    profile = data.get('profile', '')
    env_vars = data.get('env', {})
    
    # Build command
    command = service['start_command']
    if profile and service['type'] == 'spring-boot':
        if 'maven' in service.get('build_tool', ''):
            command += f' -Dspring-boot.run.profiles={profile}'
        else:
            command += f" --args='--spring.profiles.active={profile}'"
    
    # Set up environment
    env = os.environ.copy()
    env.update(env_vars)
    
    # Start process
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=service['path'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env
    )
    
    managed_services[service_name] = {
        'process': process,
        'service': service,
        'started': datetime.now().isoformat(),
        'command': command,
        'output': []
    }
    
    # Start output capture thread
    def capture_output():
        for line in iter(process.stdout.readline, ''):
            if service_name in managed_services:
                managed_services[service_name]['output'].append(line)
                if len(managed_services[service_name]['output']) > 2000:
                    managed_services[service_name]['output'].pop(0)
    
    thread = threading.Thread(target=capture_output, daemon=True)
    thread.start()
    
    add_log('info', f'Started service: {service_name}')
    
    return jsonify({
        'success': True,
        'service': service_name,
        'pid': process.pid,
        'command': command
    })


@app.route('/api/service/<service_name>/stop', methods=['POST'])
@require_auth
def api_service_stop(service_name):
    """Stop a specific service"""
    # Check if we manage it
    if service_name in managed_services:
        proc_info = managed_services[service_name]
        proc = proc_info.get('process')
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        del managed_services[service_name]
        add_log('info', f'Stopped managed service: {service_name}')
        return jsonify({'success': True})
    
    # Try to find and kill by port
    service = None
    for svc in CONFIG['services_config'].get('microservices', []) + CONFIG['services_config'].get('frontends', []):
        if svc['name'] == service_name:
            service = svc
            break
    
    if service and service.get('port'):
        try:
            subprocess.run(
                f"lsof -i :{service['port']} -t | xargs kill -9 2>/dev/null || true",
                shell=True
            )
            add_log('info', f'Stopped service on port {service["port"]}: {service_name}')
            return jsonify({'success': True})
        except:
            pass
    
    return jsonify({'error': 'Could not stop service'}), 500


@app.route('/api/service/<service_name>/restart', methods=['POST'])
@require_auth
def api_service_restart(service_name):
    """Restart a specific service"""
    # Stop first
    api_service_stop(service_name)
    time.sleep(2)
    # Start again
    return api_service_start(service_name)


@app.route('/api/service/<service_name>/output')
@require_auth
def api_service_output(service_name):
    """Get service output logs"""
    if service_name not in managed_services:
        return jsonify({'error': 'Service not managed or not found'}), 404
    
    info = managed_services[service_name]
    lines = request.args.get('lines', 100, type=int)
    
    return jsonify({
        'output': ''.join(info['output'][-lines:]),
        'total_lines': len(info['output']),
        'running': info['process'].poll() is None
    })


@app.route('/api/service/<service_name>/build', methods=['POST'])
@require_auth
def api_service_build(service_name):
    """Build a specific service"""
    service = None
    for svc in CONFIG['services_config'].get('microservices', []) + CONFIG['services_config'].get('frontends', []):
        if svc['name'] == service_name:
            service = svc
            break
    
    if not service:
        return jsonify({'error': f'Service {service_name} not found'}), 404
    
    command = service.get('build_command', '')
    if not command:
        return jsonify({'error': 'No build command configured'}), 400
    
    add_log('info', f'Building service: {service_name}')
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=service['path'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout for builds
        )
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout + result.stderr,
            'return_code': result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Build timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/services/start-all', methods=['POST'])
@require_auth
def api_services_start_all():
    """Start all services"""
    data = request.get_json() or {}
    include_frontend = data.get('include_frontend', True)
    profile = data.get('profile', '')
    
    results = []
    
    # Start microservices first
    for svc in CONFIG['services_config'].get('microservices', []):
        try:
            # Make internal request to start
            with app.test_request_context(
                f'/api/service/{svc["name"]}/start',
                method='POST',
                json={'profile': profile}
            ):
                session['authenticated'] = True
                result = api_service_start(svc['name'])
                results.append({
                    'service': svc['name'],
                    'success': True,
                    'type': 'microservice'
                })
        except Exception as e:
            results.append({
                'service': svc['name'],
                'success': False,
                'error': str(e),
                'type': 'microservice'
            })
        time.sleep(1)  # Stagger starts
    
    # Start frontends
    if include_frontend:
        for svc in CONFIG['services_config'].get('frontends', []):
            try:
                with app.test_request_context(
                    f'/api/service/{svc["name"]}/start',
                    method='POST',
                    json={}
                ):
                    session['authenticated'] = True
                    result = api_service_start(svc['name'])
                    results.append({
                        'service': svc['name'],
                        'success': True,
                        'type': 'frontend'
                    })
            except Exception as e:
                results.append({
                    'service': svc['name'],
                    'success': False,
                    'error': str(e),
                    'type': 'frontend'
                })
    
    return jsonify({'results': results})


@app.route('/api/services/stop-all', methods=['POST'])
@require_auth
def api_services_stop_all():
    """Stop all services"""
    results = []
    
    # Stop all managed services
    for name in list(managed_services.keys()):
        try:
            api_service_stop(name)
            results.append({'service': name, 'success': True})
        except Exception as e:
            results.append({'service': name, 'success': False, 'error': str(e)})
    
    return jsonify({'results': results})


@app.route('/api/execute', methods=['POST'])
@require_auth
def api_execute():
    """Execute a shell command"""
    data = request.get_json()
    command = data.get('command', '')
    cwd = data.get('cwd', CONFIG['workspace_path'])
    timeout = data.get('timeout', 60)
    
    if not command:
        return jsonify({'error': 'No command provided'}), 400
    
    add_log('info', f'Executing: {command}')
    command_history.append({
        'command': command,
        'timestamp': datetime.now().isoformat(),
        'cwd': cwd
    })
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        output = result.stdout + result.stderr
        lines = output.split('\n')
        if len(lines) > CONFIG['max_output_lines']:
            lines = lines[-CONFIG['max_output_lines']:]
            output = f"... (truncated to last {CONFIG['max_output_lines']} lines)\n" + '\n'.join(lines)
        
        return jsonify({
            'success': True,
            'output': output,
            'return_code': result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': f'Command timed out after {timeout} seconds'
        })
    except Exception as e:
        add_log('error', f'Command failed: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/files/list')
@require_auth
def api_files_list():
    """List files in a directory"""
    path = request.args.get('path', CONFIG['workspace_path'])
    
    try:
        entries = []
        for entry in os.scandir(path):
            try:
                stat = entry.stat()
                entries.append({
                    'name': entry.name,
                    'path': entry.path,
                    'is_dir': entry.is_dir(),
                    'size': stat.st_size if not entry.is_dir() else 0,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except PermissionError:
                continue
        
        entries.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        return jsonify({
            'path': path,
            'parent': str(Path(path).parent),
            'entries': entries
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/files/read')
@require_auth
def api_files_read():
    """Read a file's contents"""
    path = request.args.get('path')
    if not path:
        return jsonify({'error': 'No path provided'}), 400
    
    try:
        with open(path, 'r') as f:
            content = f.read()
        return jsonify({
            'path': path,
            'content': content,
            'size': len(content)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/files/write', methods=['POST'])
@require_auth
def api_files_write():
    """Write content to a file"""
    data = request.get_json()
    path = data.get('path')
    content = data.get('content')
    
    if not path or content is None:
        return jsonify({'error': 'Path and content required'}), 400
    
    try:
        with open(path, 'w') as f:
            f.write(content)
        add_log('info', f'File written: {path}')
        return jsonify({'success': True, 'path': path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/git/status')
@require_auth
def api_git_status():
    """Get git status"""
    cwd = request.args.get('path', CONFIG['workspace_path'])
    
    try:
        result = subprocess.run(
            'git status --porcelain',
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        
        branch = subprocess.run(
            'git branch --show-current',
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        
        return jsonify({
            'branch': branch.stdout.strip(),
            'status': result.stdout,
            'clean': len(result.stdout.strip()) == 0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
@require_auth
def api_history():
    """Get command history"""
    return jsonify({'history': command_history[-50:]})


@app.route('/api/logs')
@require_auth
def api_logs():
    """Get server logs"""
    return jsonify({'logs': log_buffer[-100:]})


@app.route('/api/cursor/open', methods=['POST'])
@require_auth
def api_cursor_open():
    """Open a file or folder in Cursor IDE"""
    data = request.get_json()
    path = data.get('path', CONFIG['workspace_path'])
    
    try:
        cmd = f'open -a "Cursor" "{path}"'
        subprocess.run(cmd, shell=True, check=True)
        add_log('info', f'Opened in Cursor: {path}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/docker/status')
@require_auth
def api_docker_status():
    """Get Docker container status"""
    try:
        result = subprocess.run(
            'docker ps --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"',
            shell=True,
            capture_output=True,
            text=True
        )
        
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    containers.append({
                        'name': parts[0],
                        'status': parts[1],
                        'ports': parts[2] if len(parts) > 2 else ''
                    })
        
        return jsonify({'containers': containers})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='Cursor Remote Agent - Multi-Service Edition')
    parser.add_argument('--port', type=int, default=CONFIG['port'],
                       help='Port to listen on')
    parser.add_argument('--host', default=CONFIG['host'],
                       help='Host to bind to')
    parser.add_argument('--password', default=CONFIG['password'],
                       help='Password for authentication')
    parser.add_argument('--workspace', default=CONFIG['workspace_path'],
                       help='Workspace path containing all projects')
    args = parser.parse_args()
    
    CONFIG['port'] = args.port
    CONFIG['host'] = args.host
    CONFIG['password'] = args.password
    CONFIG['workspace_path'] = os.path.expanduser(args.workspace)
    
    # Load/detect services
    load_services_config()
    
    services_count = len(CONFIG['services_config'].get('microservices', [])) + \
                    len(CONFIG['services_config'].get('frontends', []))
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════════╗
║     Cursor Remote Agent - Multi-Microservice Edition                   ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                         ║
║  Server running at: http://{args.host}:{args.port}                              ║
║  Password: {args.password}                                                     ║
║  Workspace: {args.workspace[:50]}                                       ║
║  Detected Services: {services_count}                                              ║
║                                                                         ║
║  Microservices:                                                         ║""")
    
    for svc in CONFIG['services_config'].get('microservices', []):
        print(f"║    • {svc['name'][:30]:<30} (port {svc['port']})                    ║")
    
    print("║                                                                         ║")
    print("║  Frontends:                                                             ║")
    
    for svc in CONFIG['services_config'].get('frontends', []):
        print(f"║    • {svc['name'][:30]:<30} (port {svc['port']})                    ║")
    
    print(f"""║                                                                         ║
║  To connect from your iPhone:                                           ║
║  1. Make sure your Mac and iPhone are on the same network               ║
║  2. Find your Mac's local IP: ifconfig | grep "inet "                   ║
║  3. Open Safari on your iPhone and go to:                               ║
║     http://YOUR_MAC_IP:{args.port}                                        ║
║                                                                         ║
╚═══════════════════════════════════════════════════════════════════════╝
    """)
    
    add_log('info', f'Server started on {args.host}:{args.port}')
    
    app.run(
        host=args.host,
        port=args.port,
        debug=False,
        threaded=True
    )


if __name__ == '__main__':
    main()
