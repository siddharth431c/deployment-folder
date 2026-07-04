#!/usr/bin/env python3
"""
Cursor Remote Agent - Control your Cursor IDE from your iPhone
A web-based remote control server for development tasks
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
    'project_path': os.environ.get('PROJECT_PATH', os.path.expanduser('~')),
    'password': os.environ.get('AGENT_PASSWORD', 'cursor123'),
    'port': int(os.environ.get('AGENT_PORT', 8765)),
    'host': os.environ.get('AGENT_HOST', '0.0.0.0'),
    'session_timeout': 3600,  # 1 hour
    'max_output_lines': 500,
    'allowed_commands': None,  # None means all commands allowed
}

# Global state for running processes
running_processes = {}
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
    return render_template('index.html', project_path=CONFIG['project_path'])


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
        'project_path': CONFIG['project_path'],
        'running_processes': len(running_processes),
        'uptime': datetime.now().isoformat()
    })


@app.route('/api/execute', methods=['POST'])
@require_auth
def api_execute():
    """Execute a shell command"""
    data = request.get_json()
    command = data.get('command', '')
    cwd = data.get('cwd', CONFIG['project_path'])
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


@app.route('/api/execute/stream', methods=['POST'])
@require_auth
def api_execute_stream():
    """Execute a command with streaming output"""
    data = request.get_json()
    command = data.get('command', '')
    cwd = data.get('cwd', CONFIG['project_path'])
    
    if not command:
        return jsonify({'error': 'No command provided'}), 400
    
    def generate():
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        proc_id = str(id(process))
        running_processes[proc_id] = process
        
        try:
            for line in iter(process.stdout.readline, ''):
                yield f"data: {json.dumps({'line': line})}\n\n"
            
            process.wait()
            yield f"data: {json.dumps({'done': True, 'return_code': process.returncode})}\n\n"
        finally:
            if proc_id in running_processes:
                del running_processes[proc_id]
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream'
    )


@app.route('/api/process/start', methods=['POST'])
@require_auth
def api_process_start():
    """Start a long-running process"""
    data = request.get_json()
    command = data.get('command', '')
    name = data.get('name', command[:30])
    cwd = data.get('cwd', CONFIG['project_path'])
    
    if not command:
        return jsonify({'error': 'No command provided'}), 400
    
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    proc_id = str(id(process))
    running_processes[proc_id] = {
        'process': process,
        'name': name,
        'command': command,
        'started': datetime.now().isoformat(),
        'output': []
    }
    
    def capture_output():
        for line in iter(process.stdout.readline, ''):
            if proc_id in running_processes:
                running_processes[proc_id]['output'].append(line)
                if len(running_processes[proc_id]['output']) > 1000:
                    running_processes[proc_id]['output'].pop(0)
    
    thread = threading.Thread(target=capture_output, daemon=True)
    thread.start()
    
    add_log('info', f'Started process: {name} (ID: {proc_id})')
    
    return jsonify({
        'success': True,
        'process_id': proc_id,
        'name': name
    })


@app.route('/api/process/list')
@require_auth
def api_process_list():
    """List running processes"""
    processes = []
    for proc_id, info in running_processes.items():
        if isinstance(info, dict):
            proc = info['process']
            processes.append({
                'id': proc_id,
                'name': info['name'],
                'command': info['command'],
                'started': info['started'],
                'running': proc.poll() is None,
                'output_lines': len(info.get('output', []))
            })
    return jsonify({'processes': processes})


@app.route('/api/process/<proc_id>/output')
@require_auth
def api_process_output(proc_id):
    """Get process output"""
    if proc_id not in running_processes:
        return jsonify({'error': 'Process not found'}), 404
    
    info = running_processes[proc_id]
    if isinstance(info, dict):
        return jsonify({
            'output': ''.join(info.get('output', [])),
            'running': info['process'].poll() is None
        })
    return jsonify({'error': 'Invalid process info'}), 500


@app.route('/api/process/<proc_id>/stop', methods=['POST'])
@require_auth
def api_process_stop(proc_id):
    """Stop a running process"""
    if proc_id not in running_processes:
        return jsonify({'error': 'Process not found'}), 404
    
    info = running_processes[proc_id]
    if isinstance(info, dict):
        proc = info['process']
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        add_log('info', f'Stopped process: {info["name"]}')
    
    return jsonify({'success': True})


@app.route('/api/files/list')
@require_auth
def api_files_list():
    """List files in a directory"""
    path = request.args.get('path', CONFIG['project_path'])
    
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


@app.route('/api/spring-boot/status')
@require_auth
def api_spring_boot_status():
    """Check Spring Boot application status"""
    try:
        result = subprocess.run(
            "ps aux | grep -E '[j]ava.*spring|[m]vn.*spring|[g]radle.*boot' | head -5",
            shell=True,
            capture_output=True,
            text=True
        )
        
        processes = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 11:
                    processes.append({
                        'pid': parts[1],
                        'cpu': parts[2],
                        'mem': parts[3],
                        'command': ' '.join(parts[10:])[:100]
                    })
        
        # Check common Spring Boot ports
        port_check = subprocess.run(
            "lsof -i :8080 -i :8081 -i :9000 2>/dev/null | grep LISTEN | head -5",
            shell=True,
            capture_output=True,
            text=True
        )
        
        ports = []
        for line in port_check.stdout.strip().split('\n'):
            if line and 'LISTEN' in line:
                parts = line.split()
                if len(parts) >= 9:
                    ports.append({
                        'process': parts[0],
                        'pid': parts[1],
                        'port': parts[8]
                    })
        
        return jsonify({
            'running': len(processes) > 0,
            'processes': processes,
            'listening_ports': ports
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/spring-boot/start', methods=['POST'])
@require_auth
def api_spring_boot_start():
    """Start Spring Boot application"""
    data = request.get_json() or {}
    cwd = data.get('path', CONFIG['project_path'])
    profile = data.get('profile', 'default')
    
    # Detect build tool
    has_maven = os.path.exists(os.path.join(cwd, 'pom.xml'))
    has_gradle = os.path.exists(os.path.join(cwd, 'build.gradle')) or \
                 os.path.exists(os.path.join(cwd, 'build.gradle.kts'))
    
    if has_maven:
        command = f"./mvnw spring-boot:run -Dspring-boot.run.profiles={profile}"
        if not os.path.exists(os.path.join(cwd, 'mvnw')):
            command = f"mvn spring-boot:run -Dspring-boot.run.profiles={profile}"
    elif has_gradle:
        command = f"./gradlew bootRun --args='--spring.profiles.active={profile}'"
        if not os.path.exists(os.path.join(cwd, 'gradlew')):
            command = f"gradle bootRun --args='--spring.profiles.active={profile}'"
    else:
        return jsonify({
            'error': 'No Maven or Gradle build file found in project path'
        }), 400
    
    # Start as background process
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    proc_id = str(id(process))
    running_processes[proc_id] = {
        'process': process,
        'name': 'Spring Boot',
        'command': command,
        'started': datetime.now().isoformat(),
        'output': []
    }
    
    def capture_output():
        for line in iter(process.stdout.readline, ''):
            if proc_id in running_processes:
                running_processes[proc_id]['output'].append(line)
                if len(running_processes[proc_id]['output']) > 2000:
                    running_processes[proc_id]['output'].pop(0)
    
    thread = threading.Thread(target=capture_output, daemon=True)
    thread.start()
    
    add_log('info', f'Started Spring Boot application (ID: {proc_id})')
    
    return jsonify({
        'success': True,
        'process_id': proc_id,
        'command': command
    })


@app.route('/api/spring-boot/stop', methods=['POST'])
@require_auth
def api_spring_boot_stop():
    """Stop Spring Boot application"""
    # Find and stop Spring Boot processes
    try:
        subprocess.run(
            "pkill -f 'java.*spring' || true",
            shell=True,
            capture_output=True
        )
        add_log('info', 'Stopped Spring Boot application')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/git/status')
@require_auth
def api_git_status():
    """Get git status"""
    cwd = request.args.get('path', CONFIG['project_path'])
    
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
    """Open a file in Cursor IDE"""
    data = request.get_json()
    path = data.get('path')
    line = data.get('line', 1)
    
    if not path:
        return jsonify({'error': 'No path provided'}), 400
    
    try:
        # Try to open in Cursor (macOS)
        cmd = f'open -a "Cursor" "{path}"'
        subprocess.run(cmd, shell=True, check=True)
        add_log('info', f'Opened in Cursor: {path}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cursor/command', methods=['POST'])
@require_auth
def api_cursor_command():
    """Send a command to Cursor via command palette simulation"""
    data = request.get_json()
    command = data.get('command')
    
    if not command:
        return jsonify({'error': 'No command provided'}), 400
    
    try:
        # Use AppleScript to send keyboard shortcuts to Cursor
        script = f'''
        tell application "Cursor"
            activate
        end tell
        delay 0.5
        tell application "System Events"
            keystroke "p" using {{command down, shift down}}
            delay 0.3
            keystroke "{command}"
            delay 0.2
            key code 36
        end tell
        '''
        subprocess.run(['osascript', '-e', script], check=True)
        add_log('info', f'Sent Cursor command: {command}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='Cursor Remote Agent')
    parser.add_argument('--port', type=int, default=CONFIG['port'],
                       help='Port to listen on')
    parser.add_argument('--host', default=CONFIG['host'],
                       help='Host to bind to')
    parser.add_argument('--password', default=CONFIG['password'],
                       help='Password for authentication')
    parser.add_argument('--project', default=CONFIG['project_path'],
                       help='Default project path')
    args = parser.parse_args()
    
    CONFIG['port'] = args.port
    CONFIG['host'] = args.host
    CONFIG['password'] = args.password
    CONFIG['project_path'] = os.path.expanduser(args.project)
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║           Cursor Remote Agent - Mobile Development Control         ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                     ║
║  Server running at: http://{args.host}:{args.port}                          ║
║  Password: {args.password}                                                 ║
║  Project: {args.project[:50]}                                       ║
║                                                                     ║
║  To connect from your iPhone:                                       ║
║  1. Make sure your Mac and iPhone are on the same network           ║
║  2. Find your Mac's local IP: ifconfig | grep "inet "               ║
║  3. Open Safari on your iPhone and go to:                           ║
║     http://YOUR_MAC_IP:{args.port}                                    ║
║                                                                     ║
╚═══════════════════════════════════════════════════════════════════╝
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
