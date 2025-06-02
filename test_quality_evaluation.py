import asyncio
import json
from pathlib import Path
import logging
from app.services.translation_quality_service import TranslationQualityService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_quality_evaluation():
    """测试翻译质量评估功能"""
    quality_service = TranslationQualityService()
    
    # 测试用例
    test_cases = [
        {
            "name": "完美翻译",
            "source": "Hello {$playerName}, welcome to the game! Your HP is <color=red>100</color>.",
            "translated": "你好 {$playerName}，欢迎来到游戏！你的生命值是 <color=red>100</color>。",
            "expected_score": 100.0
        },
        {
            "name": "标签丢失",
            "source": "Hello {$playerName}, welcome to the game! Your HP is <color=red>100</color>.",
            "translated": "你好，欢迎来到游戏！你的生命值是100。",
            "expected_score": 60.0
        },
        {
            "name": "格式错误",
            "source": "Current time: 12:34:56, Date: 2024-01-20, Price: $100.50",
            "translated": "当前时间：12点34分56秒，日期：2024年1月20日，价格：100.50元",
            "expected_score": 80.0
        },
        {
            "name": "标点错误",
            "source": "Hello, world!",
            "translated": "你好，世界",
            "expected_score": 80.0
        },
        {
            "name": "复杂标签",
            "source": "You found [item:sword_01] in the [location:chest_01]. Talk to [npc:merchant_01] to complete [quest:main_01].",
            "translated": "你在[location:chest_01]中找到了[item:sword_01]。与[npc:merchant_01]交谈以完成[quest:main_01]。",
            "expected_score": 100.0
        }
    ]
    
    print("\n开始测试翻译质量评估功能...")
    print("-" * 80)
    
    for test_case in test_cases:
        print(f"\n测试用例: {test_case['name']}")
        print(f"源文本: {test_case['source']}")
        print(f"翻译文本: {test_case['translated']}")
        
        # 执行评估
        result = await quality_service.evaluate_translation(
            source_text=test_case['source'],
            translated_text=test_case['translated']
        )
        
        # 打印评估结果
        print("\n评估结果:")
        print(f"总体评分: {result.overall_score:.1f}")
        print(f"标签保留评分: {result.tag_preservation_score:.1f}")
        print(f"格式保留评分: {result.format_preservation_score:.1f}")
        print(f"语义准确性评分: {result.semantic_accuracy_score:.1f}")
        print(f"流畅度评分: {result.fluency_score:.1f}")
        
        if result.issues:
            print("\n发现的问题:")
            for issue in result.issues:
                print(f"- {issue}")
        
        if result.suggestions:
            print("\n改进建议:")
            for suggestion in result.suggestions:
                print(f"- {suggestion}")
        
        print("-" * 80)
        
        # 保存评估结果
        job_id = f"test_{test_case['name'].lower().replace(' ', '_')}"
        quality_service.save_evaluation_result(job_id, result)
        print(f"评估结果已保存到: app/output_files/quality_evaluations/evaluation_{job_id}.json")

if __name__ == "__main__":
    # 确保输出目录存在
    output_dir = Path("app/output_files/quality_evaluations")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 运行测试
    asyncio.run(test_quality_evaluation()) 