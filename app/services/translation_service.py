from typing import Dict, List, Optional, Tuple
import json
import logging
from pathlib import Path
import asyncio
from datetime import datetime
import uuid
from app.services.translation_quality_service import TranslationQualityService, QualityScore

logger = logging.getLogger(__name__)

class TranslationService:
    """翻译服务，处理翻译请求和结果"""
    
    def __init__(self):
        self.quality_service = TranslationQualityService()
        self.output_dir = Path("app/output_files")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    async def translate_text(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "zh",
        context: Optional[Dict] = None
    ) -> Tuple[str, QualityScore]:
        """
        翻译文本并评估质量
        
        Args:
            text: 要翻译的文本
            source_lang: 源语言代码
            target_lang: 目标语言代码
            context: 翻译上下文信息
            
        Returns:
            Tuple[str, QualityScore]: (翻译后的文本, 质量评估结果)
        """
        try:
            # 1. 调用翻译API获取翻译结果
            translated_text = await self._call_translation_api(text, source_lang, target_lang, context)
            
            # 2. 评估翻译质量
            quality_score = await self.quality_service.evaluate_translation(
                text,
                translated_text,
                source_lang,
                target_lang
            )
            
            # 3. 生成任务ID
            job_id = str(uuid.uuid4())
            
            # 4. 保存翻译结果和质量评估
            self._save_translation_result(job_id, text, translated_text, quality_score)
            
            # 5. 如果质量不合格，记录警告
            if quality_score.overall_score < self.quality_service.quality_threshold:
                logger.warning(
                    f"Translation quality below threshold for job {job_id}. "
                    f"Score: {quality_score.overall_score}, "
                    f"Issues: {quality_score.issues}"
                )
            
            return translated_text, quality_score
            
        except Exception as e:
            logger.error(f"Error in translate_text: {str(e)}")
            raise
    
    async def _call_translation_api(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[Dict] = None
    ) -> str:
        """调用翻译API"""
        # TODO: 实现实际的翻译API调用
        # 这里使用模拟的翻译结果
        translations = {
            "Hello {$playerName}, welcome to the game! Your HP is <color=red>100</color>.": 
                "你好 {$playerName}，欢迎来到游戏！你的生命值是 <color=red>100</color>。",
            "Current time: 12:34:56, Date: 2024-01-20, Price: $100.50":
                "当前时间：12点34分56秒，日期：2024年1月20日，价格：100.50元",
            "You found [item:sword_01] in the [location:chest_01]. Talk to [npc:merchant_01] to complete [quest:main_01].":
                "你在[location:chest_01]中找到了[item:sword_01]。与[npc:merchant_01]交谈以完成[quest:main_01]。"
        }
        
        # 模拟API延迟
        await asyncio.sleep(0.1)
        
        # 返回预定义的翻译结果
        return translations.get(text, f"Translated: {text}")
    
    def _save_translation_result(
        self,
        job_id: str,
        source_text: str,
        translated_text: str,
        quality_score: QualityScore
    ) -> None:
        """保存翻译结果和质量评估"""
        # 1. 保存翻译结果
        translation_file = self.output_dir / "translations" / f"translation_{job_id}.json"
        translation_file.parent.mkdir(exist_ok=True)
        
        translation_data = {
            "job_id": job_id,
            "source_text": source_text,
            "translated_text": translated_text,
            "timestamp": datetime.now().isoformat()
        }
        
        with open(translation_file, "w", encoding="utf-8") as f:
            json.dump(translation_data, f, ensure_ascii=False, indent=2)
        
        # 2. 保存质量评估结果
        self.quality_service.save_evaluation_result(job_id, quality_score)
        
        logger.info(f"Saved translation result and quality evaluation for job {job_id}") 