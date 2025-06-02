import asyncio
import logging
import sys
import os
from pathlib import Path
import pandas as pd
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.tag_protection_service import TagProtectionService
from app.services.translation_job_service import create_and_process_translation_job
from app.models import TranslationJobRequest
from fastapi import BackgroundTasks
from app.services.file_service import FileService

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,  # 改为DEBUG级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print("脚本开始执行")  # 添加打印语句

async def create_test_excel():
    """创建测试用的Excel文件"""
    print("开始创建测试Excel文件")  # 添加打印语句
    test_data = {
        "SourceString": [
            "Hello {$playerName}, welcome to the game!",
            "Your current HP is <color=red>100</color>",
            "You found [item:sword_01] in the chest",
            "Talk to [npc:merchant_01] to complete [quest:main_01]",
            "You earned [achievement:first_kill]!",
            "Current time: 12:34:56",
            "Today's date: 2024-01-01",
            "Your balance: ¥1,234.56",
            "Use /help for commands",
            "Click [icon:item_sword] to equip",
            "Color code: #FF0000",
            "Format: %s, %d, %.2f",
            "Special chars: <>{}\\[]()%$#@!&*+=|\\/",
            "Currency: $100, €200, £300, ₽400"
        ]
    }
    
    # 创建测试文件
    test_file = Path("app/temp_files/test_translation.xlsx")
    print(f"测试文件路径: {test_file.absolute()}")  # 添加打印语句
    
    # 确保目录存在
    test_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"目录已创建: {test_file.parent.absolute()}")  # 添加打印语句
    
    df = pd.DataFrame(test_data)
    df.to_excel(test_file, index=False)
    print(f"Excel文件已创建: {test_file.absolute()}")  # 添加打印语句
    
    logger.info(f"Created test Excel file: {test_file}")
    return test_file

async def test_translation_with_tag_protection():
    """测试带符号保护的翻译流程"""
    try:
        print("开始测试翻译流程")  # 添加打印语句
        
        # 1. 创建测试Excel文件
        test_file = await create_test_excel()
        print(f"测试文件已创建: {test_file}")  # 添加打印语句
        
        # 2. 创建翻译任务请求
        job_request = TranslationJobRequest(
            file_id=str(test_file),
            original_filename="test_translation.xlsx",
            source_language="en",
            target_language="zh",
            original_text_column="SourceString",
            translated_text_column_name="Chinese Translation",
            zhipu_api_key="3b27bf28511a466aac7b8eb203de88f0.L7GHV5ioYKHGJqhm",
            texts_per_chunk=5
        )
        print("翻译任务请求已创建")  # 添加打印语句
        
        # 3. 创建后台任务
        background_tasks = BackgroundTasks()
        
        # 4. 创建并处理翻译任务
        logger.info("Starting translation job...")
        print("开始创建翻译任务")  # 添加打印语句
        response = await create_and_process_translation_job(job_request, background_tasks)
        print(f"翻译任务响应: {response}")  # 添加打印语句
        logger.info(f"Translation job created: {response}")
        
        # 5. 等待任务完成（这里只是示例，实际应该使用轮询或回调）
        await asyncio.sleep(2)
        
        # 6. 清理测试文件
        if test_file.exists():
            test_file.unlink()
            print(f"测试文件已删除: {test_file}")  # 添加打印语句
            logger.info(f"Removed test file: {test_file}")
        
        logger.info("Test completed successfully!")
        print("测试完成")  # 添加打印语句
        
    except Exception as e:
        print(f"测试失败: {str(e)}")  # 添加打印语句
        logger.error(f"Test failed: {str(e)}", exc_info=True)
        raise

def test_tag_protection_service():
    """单独测试TagProtectionService的功能"""
    print("开始测试标签保护服务")  # 添加打印语句
    tag_service = TagProtectionService()
    
    test_texts = [
        "Hello {$playerName}, welcome to the game!",
        "Your current HP is <color=red>100</color>",
        "You found [item:sword_01] in the chest",
        "Talk to [npc:merchant_01] to complete [quest:main_01]",
        "You earned [achievement:first_kill]!",
        "Current time: 12:34:56",
        "Today's date: 2024-01-01",
        "Your balance: ¥1,234.56",
        "Use /help for commands",
        "Click [icon:item_sword] to equip",
        "Color code: #FF0000",
        "Format: %s, %d, %.2f",
        "Special chars: <>{}\\[]()%$#@!&*+=|\\/",
        "Currency: $100, €200, £300, ₽400"
    ]
    
    logger.info("Testing TagProtectionService...")
    
    for text in test_texts:
        logger.info(f"\n测试文本: {text}")
        
        # 保护标签
        protected_text, tag_map = tag_service.protect_tags(text)
        logger.info(f"保护后的文本: {protected_text}")
        logger.info(f"标签映射: {tag_map}")
        
        # 模拟翻译（这里只是简单替换一些词）
        translated_text = protected_text.replace("Hello", "你好").replace("welcome", "欢迎")
        
        # 还原标签
        restored_text = tag_service.restore_tags(translated_text, tag_map)
        logger.info(f"恢复后的文本: {restored_text}")
        
        # 验证还原是否正确
        if text != restored_text:
            logger.warning(f"标签还原不完全匹配！\n原文: {text}\n还原: {restored_text}")
        
        logger.info("-" * 80)
    
    print("标签保护服务测试完成")  # 添加打印语句

if __name__ == "__main__":
    print("主程序开始执行")  # 添加打印语句
    # 首先测试TagProtectionService
    test_tag_protection_service()
    
    # 然后测试完整的翻译流程
    asyncio.run(test_translation_with_tag_protection())
    print("主程序执行完成")  # 添加打印语句 