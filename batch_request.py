# 创建批处理任务
create_task_url = f"{base_url}/batch"
create_task_data = {
    "input_file_id": file_id,
    "endpoint": "/v1/chat/completions",
    "completion_window": "24h"
}

print("\n创建批处理任务...")
create_task_response = requests.put(
    create_task_url,
    headers=headers,
    json=create_task_data
) 