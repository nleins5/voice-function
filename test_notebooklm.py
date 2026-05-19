import subprocess
import json

def call_mcp_tool(tool_name, arguments={}):
    process = subprocess.Popen(
        ["/Users/lananh/.local/bin/notebooklm-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        # Initialize
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        process.stdin.write(json.dumps(init_request) + "\n")
        process.stdin.flush()
        process.stdout.readline()
        
        # Call tool
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        process.stdin.write(json.dumps(tool_request) + "\n")
        process.stdin.flush()
        
        response = process.stdout.readline()
        return json.loads(response)
    finally:
        process.terminate()

if __name__ == "__main__":
    try:
        result = call_mcp_tool("notebook_list")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}")
