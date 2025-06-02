import asyncio
import logging
from app.services.translation_service import TranslationService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def test_translation_service():
    """测试翻译服务"""
    service = TranslationService()
    
    # 测试用例
    test_cases = [
        {
            "name": "完美翻译",
            "text": "Hello {$playerName}, welcome to the game! Your HP is <color=red>100</color>.",
            "expected": "你好 {$playerName}，欢迎来到游戏！你的生命值是 <color=red>100</color>。"
        },
        {
            "name": "标签丢失",
            "text": "Hello {$playerName}, welcome to the game! Your HP is <color=red>100</color>.",
            "expected": "你好，欢迎来到游戏！你的生命值是100。"
        },
        {
            "name": "格式错误",
            "text": "Current time: 12:34:56, Date: 2024-01-20, Price: $100.50",
            "expected": "当前时间：12点34分56秒，日期：2024年1月20日，价格：100.50元"
        },
        {
            "name": "复杂标签",
            "text": "You found [item:sword_01] in the [location:chest_01]. Talk to [npc:merchant_01] to complete [quest:main_01].",
            "expected": "你在[location:chest_01]中找到了[item:sword_01]。与[npc:merchant_01]交谈以完成[quest:main_01]。"
        }
    ]
    
    print("\n开始测试翻译服务...")
    print("-" * 80)
    
    for case in test_cases:
        print(f"\n测试用例: {case['name']}")
        print(f"源文本: {case['text']}")
        
        # 调用翻译服务
        translated_text, quality_score = await service.translate_text(
            case['text'],
            source_lang="en",
            target_lang="zh"
        )
        
        print(f"翻译文本: {translated_text}")
        print("\n评估结果:")
        print(f"总体评分: {quality_score.overall_score}")
        print(f"标签保留评分: {quality_score.tag_preservation_score}")
        print(f"格式保留评分: {quality_score.format_preservation_score}")
        print(f"语义准确性评分: {quality_score.semantic_accuracy_score}")
        print(f"流畅度评分: {quality_score.fluency_score}")
        
        if quality_score.issues:
            print("\n发现的问题:")
            for issue in quality_score.issues:
                print(f"- {issue}")
        
        if quality_score.suggestions:
            print("\n改进建议:")
            for suggestion in quality_score.suggestions:
                print(f"- {suggestion}")
        
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(test_translation_service()) 