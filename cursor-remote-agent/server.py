#!/usr/bin/env python3
"""
Cursor Remote Agent - Control your Cursor IDE from your iPhone
A web-based remote control server for development tasks
"""

import os
import sys
import json
import shutil
import subprocess
import threading
import time
import secrets
import hashlib
import signal
import uuid
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
    'cursor_api_key': os.environ.get('CURSOR_API_KEY', ''),
    'session_timeout': 3600,  # 1 hour
    'max_output_lines': 500,
    'allowed_commands': None,  # None means all commands allowed
    'app_url': os.environ.get('APP_URL', ''),
    'cursor_bin': os.environ.get('CURSOR_BIN', ''),
}


def get_subprocess_env():
    """Get environment variables for subprocess execution, including Cursor API key"""
    env = os.environ.copy()
    if CONFIG['cursor_api_key']:
        env['CURSOR_API_KEY'] = CONFIG['cursor_api_key']
    return env

# Global state for running processes
running_processes = {}
command_history = []
log_buffer = []
agent_runs = {}
agent_prompt_history = []


def find_cursor_bin():
    """Locate the Cursor CLI binary."""
    if CONFIG.get('cursor_bin') and os.path.isfile(CONFIG['cursor_bin']):
        return CONFIG['cursor_bin']

    candidates = [
        os.path.expanduser('~/.local/bin/cursor-agent'),
        '/Applications/Cursor.app/Contents/Resources/app/bin/cursor',
        shutil.which('cursor'),
        shutil.which('cursor-agent'),
        os.path.expanduser('~/Applications/Cursor.app/Contents/Resources/app/bin/cursor'),
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def build_agent_command(prompt, workspace, mode=None, model=None, force=True):
    """Build argv for cursor agent CLI."""
    cursor_bin = find_cursor_bin()
    if not cursor_bin:
        return None, 'Cursor CLI not found. Install Cursor or set CURSOR_BIN.'

    # cursor-agent is the agent entrypoint; cursor needs the "agent" subcommand
    is_agent_bin = cursor_bin.endswith('cursor-agent')
    cmd = [cursor_bin]
    if not is_agent_bin:
        cmd.append('agent')

    cmd.extend([
        '-p',
        '--trust',
        '--workspace', workspace,
        '--output-format', 'text',
    ])
    if force:
        cmd.append('--force')
    if mode in ('plan', 'ask'):
        cmd.extend(['--mode', mode])
    if model:
        cmd.extend(['--model', model])
    cmd.append(prompt)
    return cmd, None


def open_project_in_cursor(path):
    """Open (or focus) the project folder in the Cursor IDE."""
    cursor_bin = find_cursor_bin()
    try:
        if cursor_bin and not cursor_bin.endswith('cursor-agent'):
            subprocess.Popen(
                [cursor_bin, '--reuse-window', path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_subprocess_env(),
            )
        else:
            subprocess.Popen(
                ['open', '-a', 'Cursor', path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_subprocess_env(),
            )
        return True
    except Exception as e:
        add_log('warning', f'Could not open Cursor IDE: {e}')
        return False


def inject_prompt_into_cursor_ide(prompt):
    """Paste a prompt into Cursor's agent/chat input via AppleScript."""
    # Escape for AppleScript string
    escaped = (
        prompt
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\n', '\\n')
    )
    script = f'''
    tell application "Cursor"
        activate
    end tell
    delay 0.6
    tell application "System Events"
        tell process "Cursor"
            set frontmost to true
            -- Open Agent / Composer (Cmd+I)
            keystroke "i" using {{command down}}
            delay 0.5
            -- Select all existing input and replace
            keystroke "a" using {{command down}}
            delay 0.1
            keystroke "{escaped}"
            delay 0.3
            -- Submit
            key code 36
        end tell
    end tell
    '''
    try:
        subprocess.run(
            ['osascript', '-e', script],
            check=True,
            capture_output=True,
            text=True,
            env=get_subprocess_env(),
        )
        return True, None
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or str(e)).strip()
    except Exception as e:
        return False, str(e)


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
    return render_template(
        'index.html',
        project_path=CONFIG['project_path'],
        app_url=CONFIG.get('app_url', ''),
    )


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
            timeout=timeout,
            env=get_subprocess_env()
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
            bufsize=1,
            env=get_subprocess_env()
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
        text=True,
        env=get_subprocess_env()
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
            text=True,
            env=get_subprocess_env()
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
            text=True,
            env=get_subprocess_env()
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
        text=True,
        env=get_subprocess_env()
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
            capture_output=True,
            env=get_subprocess_env()
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
            text=True,
            env=get_subprocess_env()
        )
        
        branch = subprocess.run(
            'git branch --show-current',
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=get_subprocess_env()
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
    data = request.get_json() or {}
    path = data.get('path') or CONFIG['project_path']

    try:
        open_project_in_cursor(path)
        add_log('info', f'Opened in Cursor: {path}')
        return jsonify({'success': True, 'path': path})
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

    # Escape for AppleScript
    escaped = command.replace('\\', '\\\\').replace('"', '\\"')
    try:
        script = f'''
        tell application "Cursor"
            activate
        end tell
        delay 0.5
        tell application "System Events"
            keystroke "p" using {{command down, shift down}}
            delay 0.3
            keystroke "{escaped}"
            delay 0.2
            key code 36
        end tell
        '''
        subprocess.run(
            ['osascript', '-e', script],
            check=True,
            capture_output=True,
            env=get_subprocess_env(),
        )
        add_log('info', f'Sent Cursor command: {command}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cursor/agent', methods=['POST'])
@require_auth
def api_cursor_agent():
    """Send a prompt to the Cursor agent (CLI) against the project workspace."""
    data = request.get_json() or {}
    prompt = (data.get('prompt') or '').strip()
    workspace = data.get('workspace') or CONFIG['project_path']
    mode = data.get('mode')  # None | plan | ask
    model = data.get('model')
    force = data.get('force', True)
    open_ide = data.get('open_ide', True)
    inject_ide = data.get('inject_ide', False)
    source = data.get('source', 'text')  # text | voice

    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400

    if not os.path.isdir(workspace):
        return jsonify({'error': f'Workspace not found: {workspace}'}), 400

    cmd, err = build_agent_command(prompt, workspace, mode=mode, model=model, force=force)
    if err:
        return jsonify({'error': err}), 500

    if open_ide:
        open_project_in_cursor(workspace)

    ide_injected = False
    ide_error = None
    if inject_ide:
        ide_injected, ide_error = inject_prompt_into_cursor_ide(prompt)

    run_id = str(uuid.uuid4())
    started = datetime.now().isoformat()

    try:
        process = subprocess.Popen(
            cmd,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=get_subprocess_env(),
        )
    except Exception as e:
        add_log('error', f'Failed to start Cursor agent: {e}')
        return jsonify({'error': f'Failed to start Cursor agent: {e}'}), 500

    agent_runs[run_id] = {
        'process': process,
        'prompt': prompt,
        'workspace': workspace,
        'mode': mode or 'agent',
        'source': source,
        'started': started,
        'output': [],
        'command': cmd,
        'ide_injected': ide_injected,
        'ide_error': ide_error,
    }

    def capture_output():
        try:
            for line in iter(process.stdout.readline, ''):
                if run_id in agent_runs:
                    agent_runs[run_id]['output'].append(line)
                    if len(agent_runs[run_id]['output']) > 5000:
                        agent_runs[run_id]['output'].pop(0)
        finally:
            process.wait()
            if run_id in agent_runs:
                agent_runs[run_id]['finished'] = datetime.now().isoformat()
                agent_runs[run_id]['return_code'] = process.returncode

    thread = threading.Thread(target=capture_output, daemon=True)
    thread.start()

    history_entry = {
        'id': run_id,
        'prompt': prompt,
        'workspace': workspace,
        'mode': mode or 'agent',
        'source': source,
        'started': started,
    }
    agent_prompt_history.append(history_entry)
    if len(agent_prompt_history) > 100:
        agent_prompt_history.pop(0)

    add_log('info', f'Cursor agent started ({run_id}): {prompt[:80]}')

    return jsonify({
        'success': True,
        'run_id': run_id,
        'prompt': prompt,
        'workspace': workspace,
        'mode': mode or 'agent',
        'ide_injected': ide_injected,
        'ide_error': ide_error,
        'message': 'Prompt sent to Cursor agent on your Mac',
    })


@app.route('/api/cursor/agent/<run_id>')
@require_auth
def api_cursor_agent_status(run_id):
    """Get status and output for an agent run."""
    run = agent_runs.get(run_id)
    if not run:
        # Fall back to history-only entry
        for entry in reversed(agent_prompt_history):
            if entry['id'] == run_id:
                return jsonify({
                    'id': run_id,
                    'prompt': entry['prompt'],
                    'workspace': entry['workspace'],
                    'mode': entry['mode'],
                    'source': entry.get('source', 'text'),
                    'started': entry['started'],
                    'running': False,
                    'output': '',
                    'return_code': None,
                    'finished': None,
                })
        return jsonify({'error': 'Agent run not found'}), 404

    proc = run['process']
    running = proc.poll() is None
    return jsonify({
        'id': run_id,
        'prompt': run['prompt'],
        'workspace': run['workspace'],
        'mode': run['mode'],
        'source': run.get('source', 'text'),
        'started': run['started'],
        'running': running,
        'output': ''.join(run.get('output', [])),
        'return_code': None if running else run.get('return_code', proc.returncode),
        'finished': run.get('finished'),
        'ide_injected': run.get('ide_injected', False),
        'ide_error': run.get('ide_error'),
    })


@app.route('/api/cursor/agent/<run_id>/stop', methods=['POST'])
@require_auth
def api_cursor_agent_stop(run_id):
    """Stop a running agent."""
    run = agent_runs.get(run_id)
    if not run:
        return jsonify({'error': 'Agent run not found'}), 404

    proc = run['process']
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        add_log('info', f'Stopped Cursor agent run {run_id}')

    return jsonify({'success': True})


@app.route('/api/cursor/agent/history')
@require_auth
def api_cursor_agent_history():
    """List recent agent prompts."""
    return jsonify({'history': list(reversed(agent_prompt_history[-50:]))})


@app.route('/api/cursor/agent/active')
@require_auth
def api_cursor_agent_active():
    """List active (and recent) agent runs."""
    runs = []
    for run_id, run in agent_runs.items():
        proc = run['process']
        running = proc.poll() is None
        runs.append({
            'id': run_id,
            'prompt': run['prompt'],
            'workspace': run['workspace'],
            'mode': run['mode'],
            'source': run.get('source', 'text'),
            'started': run['started'],
            'running': running,
            'output_lines': len(run.get('output', [])),
            'return_code': None if running else run.get('return_code', proc.returncode),
        })
    runs.sort(key=lambda r: r['started'], reverse=True)
    return jsonify({'runs': runs})


@app.route('/api/settings', methods=['GET', 'POST'])
@require_auth
def api_settings():
    """Get or update runtime settings (app URL, etc.)."""
    if request.method == 'GET':
        return jsonify({
            'project_path': CONFIG['project_path'],
            'app_url': CONFIG.get('app_url', ''),
            'cursor_bin': find_cursor_bin() or '',
        })

    data = request.get_json() or {}
    if 'app_url' in data:
        CONFIG['app_url'] = (data.get('app_url') or '').strip()
    if 'project_path' in data and data['project_path']:
        path = os.path.expanduser(data['project_path'])
        if os.path.isdir(path):
            CONFIG['project_path'] = path
        else:
            return jsonify({'error': f'Path not found: {path}'}), 400

    save_run_conf()
    return jsonify({
        'success': True,
        'project_path': CONFIG['project_path'],
        'app_url': CONFIG.get('app_url', ''),
        'cursor_bin': find_cursor_bin() or '',
    })


def agent_dir():
    """Directory containing server.py / update_and_start.sh."""
    return os.path.dirname(os.path.abspath(__file__))


def save_run_conf():
    """Persist current runtime settings for update_and_start.sh."""
    conf_path = os.path.join(agent_dir(), '.run.conf')
    # Quote values so special characters in passwords are safe when sourced
    def q(value):
        return "'" + str(value).replace("'", "'\"'\"'") + "'"

    content = (
        f"PROJECT_PATH={q(CONFIG['project_path'])}\n"
        f"PASSWORD={q(CONFIG['password'])}\n"
        f"PORT={q(CONFIG['port'])}\n"
        f"APP_URL={q(CONFIG.get('app_url', ''))}\n"
        f"HOST={q(CONFIG['host'])}\n"
        f"CURSOR_API_KEY={q(CONFIG.get('cursor_api_key', ''))}\n"
    )
    with open(conf_path, 'w') as f:
        f.write(content)


@app.route('/api/self/update-and-restart', methods=['POST'])
@require_auth
def api_self_update_and_restart():
    """Install dependencies and restart this remote agent via update_and_start.sh."""
    script = os.path.join(agent_dir(), 'update_and_start.sh')
    if not os.path.isfile(script):
        return jsonify({'error': 'update_and_start.sh not found'}), 404

    save_run_conf()

    env = get_subprocess_env()
    env['DELAY_RESTART'] = '1'

    try:
        # Detach so the script can kill this process after the response is sent
        subprocess.Popen(
            ['/bin/bash', script],
            cwd=agent_dir(),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        add_log('error', f'Failed to launch update_and_start.sh: {e}')
        return jsonify({'error': str(e)}), 500

    add_log('info', 'Update & restart triggered')
    return jsonify({
        'success': True,
        'message': 'Updating dependencies and restarting. Reconnect in a few seconds.',
    })


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
    parser.add_argument('--app-url', default=CONFIG.get('app_url', ''),
                       help='URL of the app to open in a mobile browser tab')
    parser.add_argument('--cursor-api-key', default=CONFIG['cursor_api_key'],
                       help='Cursor API key for CLI authentication (can also set CURSOR_API_KEY env var)')
    args = parser.parse_args()
    
    CONFIG['port'] = args.port
    CONFIG['host'] = args.host
    CONFIG['password'] = args.password
    CONFIG['project_path'] = os.path.expanduser(args.project)
    CONFIG['app_url'] = args.app_url or CONFIG.get('app_url', '')
    CONFIG['cursor_api_key'] = args.cursor_api_key
    save_run_conf()

    cursor_api_status = (
        "Configured"
        if CONFIG['cursor_api_key']
        else "Not set (run 'agent login' on Mac or set CURSOR_API_KEY)"
    )

    print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║           Cursor Remote Agent - Mobile Development Control         ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                     ║
║  Server running at: http://{args.host}:{args.port}                          ║
║  Password: {args.password}                                                 ║
║  Project: {args.project[:50]}                                       ║
║  Cursor API Key: {cursor_api_status[:45]}                            ║
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
