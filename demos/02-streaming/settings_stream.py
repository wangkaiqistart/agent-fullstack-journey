"""Streaming Demo 的异步客户端配置。"""

# os：操作系统相关功能，这里用来读取环境变量
import os
# Path：用面向对象的方式处理文件路径，比拼接字符串更安全
from pathlib import Path

# load_dotenv：读取 .env 文件，把里面的 KEY=VALUE 加载成环境变量
from dotenv import load_dotenv
# APIError：OpenAI SDK 的“接口调用出错”异常；AsyncOpenAI：异步版客户端
from openai import APIError, AsyncOpenAI


# prefix 是环境变量名的前缀，默认 "AGENTOS_LLM"，方便以后给不同模型配不同的前缀
def create_async_client(prefix="AGENTOS_LLM"):
    # __file__ 是当前文件路径；resolve() 转成绝对路径；
    # 第一个 parent 是 02-streaming 目录，第二个 parent 是 demos 目录
    # 再拼上 "01-first-model-call"，得到第一个 demo 的目录（复用它的 .env 配置）
    demo_dir = Path(__file__).resolve().parent.parent / "01-first-model-call"
    # 先加载 01-first-model-call/.env
    # override=False：如果环境变量已经存在，不覆盖（系统里已设置的优先）
    # interpolate=False：不解析 ${XXX} 这类变量引用，值按原样读取
    load_dotenv(demo_dir / ".env", override=False, interpolate=False)
    # demo_dir.parents[1] 是项目根目录（demos 的上一级）
    # 再加载根目录的 .env；因为 override=False，前面已有的值不会被它覆盖
    load_dotenv(demo_dir.parents[1] / ".env", override=False, interpolate=False)

    # 拼出三个环境变量名：AGENTOS_LLM_BASE_URL、AGENTOS_LLM_API_KEY、AGENTOS_LLM_MODEL
    names = tuple(f"{prefix}_{suffix}" for suffix in ("BASE_URL", "API_KEY", "MODEL"))
    # 找出“没配置”或“配置成空白”的变量名；strip() 去掉首尾空格，防止只填了空格
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        # 缺哪个就明确告诉用户，而不是等到请求失败才发现
        raise ValueError("缺少环境变量：" + ", ".join(missing))

    # 这个 return 返回两个值：(客户端, 模型名)，调用方用 client, model = ... 接收
    return AsyncOpenAI(
        base_url=os.environ[names[0]],  # 模型服务的地址
        api_key=os.environ[names[1]],  # 访问密钥，相当于密码，不要提交到 Git
        timeout=60.0,  # 单次请求最多等 60 秒，超时就报错
        max_retries=0,  # 不自动重试；失败后的重试策略由项目自己控制（见 streaming_retry.py）
    ), os.environ[names[2]]


# main 是传进来的异步函数（比如 stream_chat.py 里的 main）
def run_async(main):
    # 放在函数内部导入：只有真正运行时才加载 asyncio
    import asyncio

    try:
        # asyncio.run：启动事件循环并运行异步函数，直到它结束
        # 注意是 main() 带括号：先调用得到“协程对象”，再交给 asyncio.run 执行
        asyncio.run(main())
    except APIError as error:
        # 模型服务返回了错误（如密钥错误 401、限流 429）
        # getattr(对象, 属性名, 默认值)：安全地取属性，没有就返回 None，不会报错
        status = getattr(error, "status_code", None)
        # SystemExit：让程序带着一行错误信息正常退出，而不是打印一大串报错堆栈
        # type(error).__name__ 是错误类型名；status or '未知' 表示没有状态码时显示“未知”
        # from None：隐藏原始报错堆栈，避免泄露请求细节
        raise SystemExit(f"API 调用失败：{type(error).__name__}，HTTP {status or '未知'}") from None
    except ValueError as error:
        # 参数或配置不合法（如缺少环境变量、max-output-tokens 小于 1），直接显示提示信息
        raise SystemExit(str(error)) from None
