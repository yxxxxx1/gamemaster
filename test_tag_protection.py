print("脚本启动")

import sys
import os
import logging
import traceback

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.tag_protection_service import TagProtectionService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_tag_protection():
    try:
        # 创建标签保护服务实例
        tag_service = TagProtectionService()
        
        # 测试文本列表
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
        
        # 测试每个文本的标签保护
        for text in test_texts:
            logger.info(f"\n测试文本: {text}")
            
            try:
                # 保护标签
                protected_text, tag_map = tag_service.protect_tags(text)
                logger.info(f"保护后的文本: {protected_text}")
                logger.info(f"标签映射: {tag_map}")
                
                # 模拟翻译（这里只是简单替换一些词）
                translated_text = protected_text.replace("Hello", "你好").replace("welcome", "欢迎")
                
                # 恢复标签
                restored_text = tag_service.restore_tags(translated_text, tag_map)
                logger.info(f"恢复后的文本: {restored_text}")
                
            except Exception as e:
                logger.error(f"处理文本时出错: {str(e)}")
                print(traceback.format_exc())
            
            logger.info("-" * 80)
            
    except Exception as e:
        logger.error(f"测试过程中出错: {str(e)}")
        print(traceback.format_exc())

if __name__ == "__main__":
    # 运行测试
    test_tag_protection() 