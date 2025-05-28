import time
import jwt # PyJWT library
import os

# Constants from zhipu_ai_service.py (simplified)
TOKEN_EXPIRATION_SECONDS = 3600
ZHIPU_API_BASE_URL = "https://open.bigmodel.cn/api/paas"

def generate_zhipu_token(api_key: str) -> str:
    """
    Generates a JWT token for Zhipu AI API authentication.
    The api_key is expected in the format "id.secret".
    """
    try:
        key_id, secret = api_key.split(".")
    except ValueError:
        print("ERROR: Invalid Zhipu API Key format. Expected 'id.secret'.")
        raise
    except Exception as e:
        print(f"ERROR: Error splitting API Key: {e}")
        raise

    payload = {
        "api_key": key_id,
        "exp": int(round(time.time() * 1000)) + TOKEN_EXPIRATION_SECONDS * 1000,
        "timestamp": int(round(time.time() * 1000)),
    }
    token = jwt.encode(
        payload,
        secret,
        algorithm="HS256",
        headers={"alg": "HS256", "sign_type": "SIGN"}
    )
    return token

if __name__ == "__main__":
    zhipu_api_key = input("请输入您的智谱 API Key (格式: id.secret): ")
    
    if not zhipu_api_key or "." not in zhipu_api_key:
        print("API Key 格式不正确，请确保输入的是 'id.secret' 格式。")
    else:
        try:
            generated_token = generate_zhipu_token(zhipu_api_key)
            print("\n" + "="*50)
            print("生成的 JWT 令牌 (Generated JWT Token):")
            print(generated_token)
            print("="*50 + "\n")

            # --- 构建 curl 命令 ---
            # 提示用户输入 my_test_batch.jsonl 文件的确切路径
            # 确保用户使用反斜杠 `\` 作为路径分隔符，并且 curl 正确处理它们
            print("请确保 'my_test_batch.jsonl' 文件已创建并包含正确的 JSON Lines 内容。")
            file_path_input = input(r"请输入 'my_test_batch.jsonl' 文件的完整路径 (例如: F:\gamemaster\my_test_batch.jsonl): ")
            
            # 规范化路径以确保反斜杠正确
            # 在Windows上，os.path.normpath 会将 / 转为 \
            # curl 在Windows上通常能更好地处理正斜杠 /
            # 为简单起见，我们直接要求用户提供路径，并假设他们使用适合其终端的格式
            # 或者，我们可以尝试替换，但直接让用户确认路径更可靠
            
            # 确保文件路径中的反斜杠被正确处理，尤其是在Windows的curl中。
            # PowerShell中的curl可能需要路径中的反斜杠被转义，或者直接使用正斜杠。
            # 为了简单，我们这里直接使用用户输入的路径，并建议他们调整（如果需要）。

            # 使用 `-ProgressAction SilentlyContinue` 来隐藏 PowerShell 中 curl (Invoke-WebRequest) 的进度条
            # 注意: Windows 默认的 curl 是 Invoke-WebRequest 的别名。
            # 如果用户安装了真正的 curl.exe (例如通过 Git for Windows)，则不需要此参数。
            # 我们将提供一个更通用的 curl 命令，假设用户有真正的 curl 或知道如何调整。

            print("\n" + "="*50)
            print("请在您的 PowerShell 或终端中运行以下 curl 命令：")
            print("如果您使用的是 Windows PowerShell 并且没有单独安装 curl.exe，")
            print("`curl` 实际上是 `Invoke-WebRequest` 的别名。")
            print("为避免进度条，可以考虑在命令前加上 `curl.exe` (如果已安装并配置在PATH中)")
            print("或者在 PowerShell 7+ 中使用 `-ProgressAction SilentlyContinue`，但这对文件上传 (-F) 可能不直接适用。")
            print("最可靠的是使用 Git Bash 或确保您调用的是真正的 curl.exe。")
            print("="*50 + "\n")
            
            # 构建一个更标准的 curl 命令
            # 在PowerShell中，如果路径包含空格，需要用引号括起来。
            # @ 符号后的文件路径在不同系统和curl版本中处理方式略有不同。
            # 我们先生成一个标准的，用户可能需要根据其环境微调。
            
            # 尝试生成 PowerShell 友好的路径 (尽管 curl 对正斜杠通常更宽容)
            # file_path_for_curl = file_path_input.replace("\\", "/") # 转换为正斜杠

            print("curl -X POST \\")
            print(f'     "{ZHIPU_API_BASE_URL}/v4/files" \\')
            print(f'     -H "Authorization: Bearer {generated_token}" \\')
            print(f'     -F "purpose=batch" \\')
            # 在PowerShell中，如果路径包含特殊字符或空格，建议用单引号或双引号包裹
            # 为了确保跨平台兼容性，以及处理Windows路径，这里直接使用用户输入的路径
            # 如果路径中有反斜杠，PowerShell的`curl` (Invoke-WebRequest) 可能需要它们被转义成 `\\`
            # 但真正的 `curl.exe` 通常不需要。
            # 我们将假设用户能处理其特定终端的路径问题。
            print(f'     -F "file=@\\"{file_path_input}\\""') 
            # 最后的 ;type=application/jsonl 可能会导致问题，某些 curl 版本不支持在 -F 中直接指定 type
            # 如果上面的命令不行，可以尝试去掉 ;type=... 部分，或者使用 -H "Content-Type: multipart/form-data" 配合 -T (上传原始文件)
            # 但 -F 是用于表单上传的标准方式。
            # 另一种方法是: -F "file=@\"C:\path\to\file.jsonl\";type=application/jsonl"
            # 为简单起见，我们先不加 type，让服务器根据 .jsonl 和 purpose 推断
            # 更新：智谱文档明确指出需要 `application/jsonl`，所以应该包含它。
            # PowerShell中，分号是命令分隔符，所以直接用 ;type=... 可能会有问题。
            # 让我们尝试一个更安全的格式，如果不行再调整：
            print(f'     # 如果上面的 -F "file=..." 行不工作，特别是 type 部分，尝试下面的变体:')
            print(f'     # VARIANT 1 (显式 type，需要 curl 支持):')
            print(f'     # -F "file=@\\"{file_path_input}\\";type=application/jsonl" ')
            print(f'     # VARIANT 2 (如果服务器能从扩展名推断，去掉 type):')
            print(f'     # -F "file=@\\"{file_path_input}\\"" ')
            print("\n" + "="*50)
            print("请将上面 `curl` 命令中的令牌和文件路径替换为实际值后执行。")
            print(f"确保 '{file_path_input}' 是 `my_test_batch.jsonl` 的正确路径。")
            print("观察 `curl` 命令的输出，看是否仍然是 'method 不正确: null' 或其他错误。")
            print("="*50)

        except Exception as e:
            print(f"\n发生错误 (An error occurred): {e}")
