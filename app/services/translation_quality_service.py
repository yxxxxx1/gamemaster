from typing import Dict, List, Optional, Tuple
import re
from dataclasses import dataclass
import json
from pathlib import Path
import logging
from app.services.tag_protection_service import TagProtectionService
import datetime
from collections import Counter
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass
class QualityScore:
    """翻译质量评分结果"""
    overall_score: float  # 总体评分 (0-100)
    tag_preservation_score: float  # 标签保留评分 (0-100)
    format_preservation_score: float  # 格式保留评分 (0-100)
    semantic_accuracy_score: float  # 语义准确性评分 (0-100)
    fluency_score: float  # 流畅度评分 (0-100)
    issues: List[str]  # 发现的问题列表
    suggestions: List[str]  # 改进建议

class TranslationQualityService:
    """翻译质量评估服务"""
    
    def __init__(self):
        self.tag_service = TagProtectionService()
        self.quality_threshold = 80.0  # 质量合格阈值
        
        # 评分权重
        self.score_weights = {
            'tag_preservation': 0.6,    # 标签保留权重
            'format_preservation': 0.2,  # 格式保留权重
            'semantic_accuracy': 0.1,    # 语义准确性权重
            'fluency': 0.1              # 流畅度权重
        }
        
        # 常见格式模式
        self.format_patterns = {
            'date': [
                r'\d{4}-\d{2}-\d{2}',  # 标准日期格式
                r'\d{4}年\d{1,2}月\d{1,2}日',  # 中文日期格式
            ],
            'time': [
                r'\d{2}:\d{2}:\d{2}',  # 标准时间格式
                r'\d{1,2}点\d{1,2}分\d{1,2}秒',  # 中文时间格式
            ],
            'currency': [
                r'[¥$€£₽]\d+(?:,\d{3})*(?:\.\d{2})?',  # 标准货币格式
                r'\d+(?:,\d{3})*(?:\.\d{2})?[元圆]',  # 中文货币格式
            ],
            'percentage': [
                r'\d+(?:\.\d+)?%',  # 标准百分比格式
                r'\d+(?:\.\d+)?%',  # 中文百分比格式
            ],
            'number': [
                r'\d+(?:,\d{3})*(?:\.\d+)?',  # 标准数字格式
                r'\d+(?:,\d{3})*(?:\.\d+)?',  # 中文数字格式
            ],
            'email': [
                r'[\w\.-]+@[\w\.-]+\.\w+',  # 邮箱格式
            ],
            'url': [
                r'https?://[\w\.-]+\.\w+(?:/[\w\.-]+)*',  # URL格式
            ],
        }
        
        # 常见问题模式
        self.issue_patterns = {
            'missing_tags': r'<[^>]+>|\[[^\]]+\]|\{[^}]+\}',  # 缺失的标签
            'broken_format': r'%[sd]|{[\d]+}|\[[\d]+\]',  # 损坏的格式
            'inconsistent_case': r'[A-Z]{2,}|[a-z]{2,}',  # 大小写不一致
            'extra_spaces': r'\s{2,}',  # 多余的空格
            'missing_punctuation': r'[.!?。！？]$',  # 缺失的标点
        }
        
        # 标点符号映射
        self.punctuation_map = {
            'en': ['.', '!', '?'],  # 英文标点
            'zh': ['。', '！', '？'],  # 中文标点
        }

    async def evaluate_translation(
        self,
        source_text: str,
        translated_text: str,
        source_lang: str = "en",
        target_lang: str = "zh"
    ) -> QualityScore:
        """
        评估翻译质量
        
        Args:
            source_text: 源文本
            translated_text: 翻译后的文本
            source_lang: 源语言代码
            target_lang: 目标语言代码
            
        Returns:
            QualityScore: 质量评分结果
        """
        issues = []
        suggestions = []
        
        # 1. 评估标签保留
        tag_score, tag_issues = self._evaluate_tag_preservation(source_text, translated_text)
        issues.extend(tag_issues)
        
        # 2. 评估格式保留
        format_score, format_issues = self._evaluate_format_preservation(source_text, translated_text)
        issues.extend(format_issues)
        
        # 3. 评估语义准确性
        semantic_score, semantic_issues = await self._evaluate_semantic_accuracy(
            source_text, translated_text, source_lang, target_lang
        )
        issues.extend(semantic_issues)
        
        # 4. 评估流畅度
        fluency_score, fluency_issues = self._evaluate_fluency(translated_text, target_lang)
        issues.extend(fluency_issues)
        
        # 5. 计算加权总体评分
        overall_score = min(100.0, (
            tag_score * self.score_weights['tag_preservation'] +
            format_score * self.score_weights['format_preservation'] +
            semantic_score * self.score_weights['semantic_accuracy'] +
            fluency_score * self.score_weights['fluency']
        ))
        
        # 6. 生成改进建议
        suggestions = self._generate_suggestions(issues, overall_score)
        
        return QualityScore(
            overall_score=overall_score,
            tag_preservation_score=tag_score,
            format_preservation_score=format_score,
            semantic_accuracy_score=semantic_score,
            fluency_score=fluency_score,
            issues=issues,
            suggestions=suggestions
        )

    async def evaluate_excel_translations(
        self,
        excel_path: str,
        source_col: str,
        target_col: str,
        source_lang: str = "en",
        target_lang: str = "zh"
    ) -> pd.DataFrame:
        """
        评估Excel文件中的翻译质量
        
        Args:
            excel_path: Excel文件路径
            source_col: 源文本列名
            target_col: 翻译文本列名
            source_lang: 源语言代码
            target_lang: 目标语言代码
            
        Returns:
            pd.DataFrame: 包含评估结果的DataFrame
        """
        # 读取Excel文件
        df = pd.read_excel(excel_path)
        
        # 确保列存在
        if source_col not in df.columns or target_col not in df.columns:
            raise ValueError(f"列 {source_col} 或 {target_col} 不存在于Excel文件中")
        
        # 创建结果列
        df['overall_score'] = 0.0
        df['tag_preservation_score'] = 0.0
        df['format_preservation_score'] = 0.0
        df['semantic_accuracy_score'] = 0.0
        df['fluency_score'] = 0.0
        df['issues'] = ''
        df['suggestions'] = ''
        
        # 对每一行进行评估
        for idx, row in df.iterrows():
            try:
                # 获取源文本和翻译文本
                source_text = str(row[source_col])
                translated_text = str(row[target_col])
                
                # 评估翻译质量
                quality_score = await self.evaluate_translation(
                    source_text=source_text,
                    translated_text=translated_text,
                    source_lang=source_lang,
                    target_lang=target_lang
                )
                
                # 更新结果
                df.at[idx, 'overall_score'] = quality_score.overall_score
                df.at[idx, 'tag_preservation_score'] = quality_score.tag_preservation_score
                df.at[idx, 'format_preservation_score'] = quality_score.format_preservation_score
                df.at[idx, 'semantic_accuracy_score'] = quality_score.semantic_accuracy_score
                df.at[idx, 'fluency_score'] = quality_score.fluency_score
                df.at[idx, 'issues'] = '; '.join(quality_score.issues)
                df.at[idx, 'suggestions'] = '; '.join(quality_score.suggestions)
                
            except Exception as e:
                logger.error(f"评估第 {idx+1} 行时出错: {str(e)}")
                df.at[idx, 'issues'] = f"评估出错: {str(e)}"
        
        return df

    def _evaluate_tag_preservation(self, source_text: str, translated_text: str) -> Tuple[float, List[str]]:
        """评估标签保留情况（内容和类型完整性为主，顺序不一致只警告）"""
        issues = []
        
        # 提取源文本和译文中的标签
        source_tags = self.tag_service.extract_tags(source_text)
        translated_tags = self.tag_service.extract_tags(translated_text)

        # 标签类型+ID提取函数
        def tag_key(tag):
            m = re.match(r'\[(\w+):([^\]]+)\]', tag)
            return m.groups() if m else tag
        src_keys = [tag_key(t) for t in source_tags]
        tgt_keys = [tag_key(t) for t in translated_tags]
        src_counter = Counter(src_keys)
        tgt_counter = Counter(tgt_keys)
        if src_counter != tgt_counter:
            issues.append("标签内容或类型不完整或不一致")
        # 顺序不一致只做警告
        if src_keys != tgt_keys and src_counter == tgt_counter:
            issues.append("标签顺序与原文不一致（仅警告）")
        # 计算得分
        score = 100.0 if not issues else max(0.0, 100.0 - (len(issues) * 20.0))
        return score, issues

    def _evaluate_format_preservation(self, source_text: str, translated_text: str) -> Tuple[float, List[str]]:
        """评估格式保留情况（允许日期格式本地化，数字内容一致即可）"""
        issues = []
        
        # 检查各种格式模式
        for format_name, patterns in self.format_patterns.items():
            source_formats = []
            translated_formats = []
            
            # 收集源文本中的格式
            for pattern in patterns:
                source_formats.extend(re.findall(pattern, source_text))
            
            # 收集翻译文本中的格式
            for pattern in patterns:
                translated_formats.extend(re.findall(pattern, translated_text))
            
            # 检查格式数量
            if len(source_formats) != len(translated_formats):
                issues.append(f"{format_name}格式数量不匹配: 源文本 {len(source_formats)} 个, 翻译后 {len(translated_formats)} 个")
            else:
                # 检查格式内容
                for src_fmt, trans_fmt in zip(source_formats, translated_formats):
                    # 对于数字格式，忽略前导零和千位分隔符
                    if format_name == 'number':
                        src_num = src_fmt.replace(',', '').lstrip('0')
                        trans_num = trans_fmt.replace(',', '').lstrip('0')
                        if src_num != trans_num:
                            issues.append(f"{format_name}格式不一致: {src_fmt} -> {trans_fmt}")
                    # 对于日期格式，数字内容一致即可
                    elif format_name == 'date':
                        src_date = ''.join(re.findall(r'\d+', src_fmt))
                        trans_date = ''.join(re.findall(r'\d+', trans_fmt))
                        if src_date != trans_date:
                            issues.append(f"{format_name}格式不一致: {src_fmt} -> {trans_fmt}")
                    # 对于时间格式，允许本地化转换
                    elif format_name == 'time':
                        src_time = re.sub(r'[^\d]', '', src_fmt)
                        trans_time = re.sub(r'[^\d]', '', trans_fmt)
                        if src_time != trans_time:
                            issues.append(f"{format_name}格式不一致: {src_fmt} -> {trans_fmt}")
                    # 对于货币格式，允许本地化转换
                    elif format_name == 'currency':
                        src_amount = re.sub(r'[^\d.]', '', src_fmt)
                        trans_amount = re.sub(r'[^\d.]', '', trans_fmt)
                        if src_amount != trans_amount:
                            issues.append(f"{format_name}格式不一致: {src_fmt} -> {trans_fmt}")
                    # 对于其他格式，严格比较
                    else:
                        if src_fmt != trans_fmt:
                            issues.append(f"{format_name}格式不一致: {src_fmt} -> {trans_fmt}")
        
        # 计算得分：如果没有问题，得分为100；每有一个问题扣20分
        score = 100.0 if not issues else max(0.0, 100.0 - (len(issues) * 20.0))
        return score, issues

    async def _evaluate_semantic_accuracy(
        self,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str
    ) -> Tuple[float, List[str]]:
        """评估语义准确性"""
        issues = []
        
        # 检查关键信息是否保留
        key_info_patterns = {
            'numbers': r'\d+',  # 数字
            'proper_nouns': r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',  # 专有名词（支持多词）
            'abbreviations': r'[A-Z]{2,}',  # 缩写
            'special_terms': r'[A-Za-z]+(?:_[A-Za-z]+)+',  # 特殊术语（如item_sword）
        }
        
        for info_type, pattern in key_info_patterns.items():
            source_info = re.findall(pattern, source_text)
            translated_info = re.findall(pattern, translated_text)
            
            # 对于数字，忽略前导零
            if info_type == 'numbers':
                source_info = [str(int(num)) for num in source_info]
                translated_info = [str(int(num)) for num in translated_info]
            
            # 对于专有名词和缩写，转换为小写进行比较
            elif info_type in ['proper_nouns', 'abbreviations']:
                source_info = [info.lower() for info in source_info]
                translated_info = [info.lower() for info in translated_info]
                
                # 对于中文文本，忽略专有名词和缩写的检查
                if target_lang == 'zh':
                    continue
            
            # 对于特殊术语，保持原样比较
            elif info_type == 'special_terms':
                pass
            
            # 检查数量是否匹配
            if len(source_info) != len(translated_info):
                issues.append(f"{info_type}数量不匹配: 源文本 {len(source_info)} 个, 翻译后 {len(translated_info)} 个")
            else:
                # 检查内容是否匹配
                for src_info, trans_info in zip(source_info, translated_info):
                    if src_info != trans_info:
                        issues.append(f"{info_type}内容不一致: {src_info} -> {trans_info}")
        
        # 计算得分：如果没有问题，得分为100；每有一个问题扣20分
        score = 100.0 if not issues else max(0.0, 100.0 - (len(issues) * 20.0))
        return score, issues

    def _evaluate_fluency(self, translated_text: str, target_lang: str) -> Tuple[float, List[str]]:
        """评估翻译流畅度（不再提示标点符号问题）"""
        issues = []
        # 检查常见问题
        for issue_name, pattern in self.issue_patterns.items():
            if re.search(pattern, translated_text):
                if issue_name == 'inconsistent_case' and target_lang == 'zh':
                    continue
                if issue_name == 'missing_tags':
                    continue
                if issue_name == 'missing_punctuation':
                    continue  # 移除missing_punctuation问题
                issues.append(f"发现{issue_name}问题")
        # 不再检查句子结尾标点符号
        if re.search(r'\s{2,}', translated_text):
            issues.append("存在多余空格")
        score = 100.0 if not issues else max(0.0, 100.0 - (len(issues) * 20.0))
        return score, issues

    def _generate_suggestions(self, issues: List[str], overall_score: float) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        # 基于问题生成建议
        for issue in issues:
            if "标签" in issue:
                suggestions.append("请确保所有标签都被正确保留")
            elif "格式" in issue:
                suggestions.append("请保持数字、日期等格式的一致性")
            elif "关键信息" in issue:
                suggestions.append("请确保所有关键信息都被准确翻译")
            elif "标点" in issue:
                suggestions.append("请检查标点符号的使用")
            elif "空格" in issue:
                suggestions.append("请检查并删除多余的空格")
        
        # 基于总体评分生成建议
        if overall_score < self.quality_threshold:
            suggestions.append("翻译质量未达到标准，建议进行人工审核")
        
        # 去重
        return list(dict.fromkeys(suggestions))

    def save_evaluation_result(self, job_id: str, evaluation_result: QualityScore) -> None:
        """保存评估结果"""
        result_dir = Path("app/output_files/quality_evaluations")
        result_dir.mkdir(parents=True, exist_ok=True)
        
        result_file = result_dir / f"evaluation_{job_id}.json"
        
        result_dict = {
            "job_id": job_id,
            "overall_score": evaluation_result.overall_score,
            "tag_preservation_score": evaluation_result.tag_preservation_score,
            "format_preservation_score": evaluation_result.format_preservation_score,
            "semantic_accuracy_score": evaluation_result.semantic_accuracy_score,
            "fluency_score": evaluation_result.fluency_score,
            "issues": evaluation_result.issues,
            "suggestions": evaluation_result.suggestions,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved quality evaluation result for job {job_id}")

    def save_excel_evaluation_result(self, df: pd.DataFrame, output_path: str) -> None:
        """
        保存Excel评估结果
        
        Args:
            df: 包含评估结果的DataFrame
            output_path: 输出文件路径
        """
        # 创建输出目录
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存Excel文件
        df.to_excel(output_path, index=False)
        logger.info(f"Saved Excel evaluation result to {output_path}") 