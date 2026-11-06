import asyncio
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def chat(messages, tools, model, context, *, num_predict=512):
    endpoint = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    payload = {'model': model, 'messages': messages, 'tools': tools, 'stream': False,
               'think': False, 'keep_alive': '5m',
               'options': {'num_ctx': context, 'temperature': 0, 'num_predict': num_predict}}
    request = Request(endpoint + '/api/chat', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=180) as response:
        result = json.load(response)
    return result


async def run(task, model=None, context=None):
    specification = json.loads(task)
    if set(specification) != {'request_id', 'prompt', 'workspace'}:
        raise ValueError('Task JSON must contain exactly request_id, prompt, workspace')
    model = model or os.getenv('HARNESS_MODEL', 'qwen3.8:27b')
    context = context or int(os.getenv('HARNESS_CONTEXT', '8192'))
    messages = [{'role': 'system', 'content':
                 'You are a local request dispatcher. Use adapter_capabilities first. '
                 'Prepare exactly the user requested draft with prepare_request, preserving the supplied '
                 'UUID, prompt and workspace. Check request_status after preparation. '
                 'Never claim a draft was submitted, executed, or completed. No UI actions are available.'},
                {'role': 'user', 'content': task}]
    transcript = {'model': model, 'context': context, 'think': False, 'steps': []}
    params = StdioServerParameters(command=sys.executable,
                                   args=['-m', 'desktop_harness.server'], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            catalog = await session.list_tools()
            allow = {'adapter_capabilities', 'prepare_request', 'request_status'}
            tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description,
                      'parameters': t.inputSchema}} for t in catalog.tools if t.name in allow]
            for _ in range(6):
                start = time.monotonic()
                response = await asyncio.to_thread(chat, messages, tools, model, context)
                message = response['message']
                messages.append(message)
                step = {'wall_seconds': round(time.monotonic() - start, 3),
                        'message': message, 'metrics': {k: response.get(k) for k in (
                            'total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration',
                            'eval_count', 'eval_duration')}}
                transcript['steps'].append(step)
                calls = message.get('tool_calls', [])
                if not calls:
                    transcript['final'] = message.get('content', '')
                    return transcript
                # Serialize tool calls: models never choose execution order or bypass the allowlist.
                for call in calls:
                    function = call['function']
                    name = function['name']
                    if name not in allow:
                        raise ValueError('Model requested an unknown tool')
                    arguments = function['arguments']
                    if name == 'prepare_request' and arguments != specification:
                        raise ValueError('Model altered the authorized draft; nothing prepared')
                    if name == 'request_status' and arguments != {'request_id': specification['request_id']}:
                        raise ValueError('Model attempted to read a different request')
                    result = await session.call_tool(name, function['arguments'])
                    content = result.model_dump(mode='json', exclude_none=True)
                    step.setdefault('tool_results', []).append({'name': name, 'result': content})
                    messages.append({'role': 'tool', 'tool_name': name, 'content': json.dumps(content)})
            raise RuntimeError('Tool-loop step limit reached; no automatic retry or submission')
