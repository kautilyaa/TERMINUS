import asyncio
import subprocess
import platform
import os
import json
import argparse
from typing import Any, Dict, List, Optional
import sys
import os
print("Python sys.path:", sys.path)

from fastmcp import FastMCP
# import sys
print("FASTMCP resolved from:", __import__('fastmcp').__file__, file=sys.stderr)

# Initialize the FastMCP server
mcp = FastMCP("Terminal MCP Server")

# Store the current working directory
current_directory = os.getcwd()

def get_shell_command():
    """Get the appropriate shell command based on the operating system"""
    system = platform.system()
    if system == "Darwin":  # macOS
        return ["/bin/bash", "-c"]
    elif system == "Windows":
        return ["cmd.exe", "/c"]
    else:  # Linux/Unix
        return ["/bin/bash", "-c"]

async def run_command(command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run a shell command and return the result"""
    try:
        shell_cmd = get_shell_command()
        
        # Handle directory changes
        if command.startswith("cd "):
            new_dir = command[3:].strip()
            if os.path.isabs(new_dir):
                target_dir = new_dir
            else:
                target_dir = os.path.join(cwd or current_directory, new_dir)
            
            if os.path.exists(target_dir) and os.path.isdir(target_dir):
                return {
                    "stdout": f"Changed directory to: {target_dir}",
                    "stderr": "",
                    "return_code": 0,
                    "new_cwd": os.path.abspath(target_dir)
                }
            else:
                return {
                    "stdout": "",
                    "stderr": f"Directory not found: {target_dir}",
                    "return_code": 1,
                    "new_cwd": cwd or current_directory
                }
        
        # For Windows, handle some command translations
        if platform.system() == "Windows":
            # Translate common Unix commands to Windows equivalents
            command_map = {
                "ls": "dir",
                "pwd": "cd",
                "cat": "type",
                "rm": "del",
                "clear": "cls",
                "mkdir": "mkdir",
                "touch": "echo. >",
            }
            
            cmd_parts = command.split()
            if cmd_parts[0] in command_map:
                cmd_parts[0] = command_map[cmd_parts[0]]
                command = " ".join(cmd_parts)
        
        # Run the command
        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or current_directory
        )
        
        stdout, stderr = await process.communicate()
        
        return {
            "stdout": stdout.decode('utf-8', errors='replace'),
            "stderr": stderr.decode('utf-8', errors='replace'),
            "return_code": process.returncode,
            "new_cwd": cwd or current_directory
        }
        
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error executing command: {str(e)}",
            "return_code": -1,
            "new_cwd": cwd or current_directory
        }

@mcp.tool()
async def run_terminal_command(command: str, working_directory: Optional[str] = None) -> str:
    """Execute a command in the terminal
    
    Args:
        command: The command to execute in the terminal
        working_directory: The working directory to execute the command in (optional)
    """
    global current_directory
    
    working_dir = working_directory or current_directory
    result = await run_command(command, working_dir)
    
    # Update current directory if cd command was successful
    if command.startswith("cd ") and result["return_code"] == 0:
        current_directory = result["new_cwd"]
    
    output = f"Command: {command}\n"
    output += f"Working Directory: {working_dir}\n"
    output += f"Return Code: {result['return_code']}\n\n"
    
    if result["stdout"]:
        output += f"Output:\n{result['stdout']}\n"
    
    if result["stderr"]:
        output += f"Error:\n{result['stderr']}\n"
    
    return output

@mcp.tool()
async def get_system_info() -> str:
    """Get information about the current system"""
    info = {
        "system": platform.system(),
        "node": platform.node(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "current_directory": current_directory
    }
    
    return json.dumps(info, indent=2)

@mcp.tool()
async def read_file(path: str) -> str:
    """Read the contents of a file
    
    Args:
        path: The path to the file to read
    """
    try:
        if not os.path.isabs(path):
            path = os.path.join(current_directory, path)
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return f"File contents of {path}:\n\n{content}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
async def write_file(path: str, content: str) -> str:
    """Write content to a file
    
    Args:
        path: The path to the file to write
        content: The content to write to the file
    """
    try:
        if not os.path.isabs(path):
            path = os.path.join(current_directory, path)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return f"Successfully wrote to file: {path} \n\n{content}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='show Terminal MCP Server')
    parser.add_argument('--transport', choices=['stdio', 'http', 'sse'], default='sse',
                       help='Transport type (stdio, http, or sse)')
    parser.add_argument('--host', default='localhost', help='Host for HTTP/SSE transport')
    parser.add_argument('--port', type=int, default=8000, help='Port for HTTP/SSE transport')
    
    args = parser.parse_args()
    
    if args.transport == 'http':
        # Run with HTTP transport
        import asyncio
        asyncio.run(mcp.run_http_async(host=args.host, port=args.port))
    elif args.transport == 'sse':
        # Run with SSE transport
        import asyncio
        asyncio.run(mcp.run_sse_async(host=args.host, port=args.port))
    else:
        # Run with stdio transport (default)
        mcp.run()

if __name__ == "__main__":
    main()