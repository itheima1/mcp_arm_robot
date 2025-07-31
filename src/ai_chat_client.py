from mcp import ClientSession
from mcp.client.sse import sse_client
from openai import OpenAI
import asyncio
import json

# 初始化DeepSeek API客户端
client = OpenAI(api_key="sk-6bc37dec91f84ed19278eb9c2ed9cd40", base_url="https://api.deepseek.com")

# 工具类型映射
TYPE_MAPPING = {
    "integer": "integer",
    "string": "string",
    "number": "number",
    "boolean": "boolean"
}

def convert_tool_to_openai_format(tool):
    """将MCP工具格式转换为OpenAI格式"""
    # 根据错误信息，tools_list中的元素是元组，而不是对象
    # 从输出日志看，工具信息是以Tool(name='add', description='两数相加', inputSchema={...})的形式返回的
    # 我们需要解析这个字符串来获取工具信息
    
    properties = {}
    required = []
    
    # 获取工具名称和描述
    name = tool.name if hasattr(tool, 'name') else str(tool)
    description = tool.description if hasattr(tool, 'description') else ""
    
    # 解析输入参数
    input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}
    
    if input_schema and isinstance(input_schema, dict):
        if 'properties' in input_schema:
            for param_name, param_info in input_schema['properties'].items():
                param_type = param_info.get('type', 'string')
                openai_type = TYPE_MAPPING.get(param_type, 'string')
                
                properties[param_name] = {
                    "type": openai_type,
                    "description": param_info.get('title', f"{param_name}参数")
                }
            
        if 'required' in input_schema:
            required = input_schema['required']
    
    # 创建OpenAI格式的工具描述
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }

async def chat_with_ai():
    """与AI聊天并允许其调用工具"""
    # 连接到MCP服务器
    async with sse_client(url="http://localhost:8000/sse") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            
            # 获取可用工具并转换为OpenAI格式
            tools_list = await session.list_tools()
            
            # 打印工具名称
            if hasattr(tools_list, 'tools'):
                tool_names = [tool.name for tool in tools_list.tools]
                print("工具名称:")
                for name in tool_names:
                    print(f"- {name}")
            
            # 修改这里的处理逻辑，直接从tools_list.tools获取工具列表
            # 根据错误信息和输出日志，tools_list是一个包含meta、nextCursor和tools属性的对象
            openai_tools = []
            if hasattr(tools_list, 'tools'):
                openai_tools = [convert_tool_to_openai_format(tool) for tool in tools_list.tools]
                print("预期格式")
            else:
                print (" 如果tools_list不是预期的格式，尝试直接遍历它")
                try:
                    openai_tools = [convert_tool_to_openai_format(tool) for tool in tools_list]
                except Exception as e:
                    print(f"转换工具格式时出错: {e}")
                    # 如果无法处理，使用空列表
                    openai_tools = []
            
            print(f"为大模型准备的工具描述: {json.dumps(openai_tools, ensure_ascii=False, indent=2)}")
            
            # 聊天历史
            messages = [
                {"role": "system", "content": "你是一个有用的助手，可以使用工具来帮助用户。当需要计算时，请使用提供的工具函数。"}
            ]
            
            print("开始与AI聊天 (输入'退出'结束对话):")
            
            while True:
                # 获取用户输入
                user_input = input("用户: ")
                if user_input.lower() == "退出":
                    break
                
                # 添加用户消息到历史
                messages.append({"role": "user", "content": user_input})
                
                # 调用AI获取响应
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto"
                )
                
                response_message = response.choices[0].message
                messages.append(response_message)
                
                # 检查是否需要调用工具
                if response_message.tool_calls:
                    # 处理每个工具调用
                    for tool_call in response_message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        
                        print(f"AI正在调用工具: {function_name}，参数: {function_args}")
                        
                        # 调用MCP工具
                        tool_result = await call_mcp_tool(session, function_name, function_args)
                        
                        # 将工具结果添加到消息历史
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": str(tool_result)
                        })
                    
                    # 再次调用AI，让它处理工具结果
                    second_response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=messages
                    )
                    
                    assistant_response = second_response.choices[0].message.content
                    messages.append({"role": "assistant", "content": assistant_response})
                    print(f"AI: {assistant_response}")
                else:
                    # 直接显示AI响应
                    print(f"AI: {response_message.content}")

async def call_mcp_tool(session, tool_name, arguments):
    """调用MCP服务器上的工具"""
    result = await session.call_tool(tool_name, arguments=arguments)
    return result.content[0].text

if __name__ == "__main__":
    asyncio.run(chat_with_ai())