from typing import Dict, List, Tuple, Optional
import re
from dataclasses import dataclass
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

@dataclass
class TagInfo:
    """存储标签的详细信息"""
    original_tag: str  # 原始标签
    placeholder: str   # 占位符
    start_pos: int    # 在原文中的起始位置
    end_pos: int      # 在原文中的结束位置
    pattern_name: str # 匹配到的模式名称
    priority: int     # 优先级，数字越大优先级越高

class TagProtectionService:
    """标签保护服务，用于在翻译前保护特殊标签和符号"""
    
    def __init__(self):
        # 定义标签模式及其优先级
        self.patterns = {
            # 游戏特定标签（高优先级）
            "brace_variables": (r"{\$.*?}", 100),  # {$variable}
            "unity_rich_text": (r"<\/?(b|i|size|color|material|quad|sprite|link|nobr|page|indent|align|mark|mspace|width|style|gradient|cspace|font|voffset|line-height|pos|space|noparse|uppercase|lowercase|smallcaps|sup|sub)(=[^>]*)?>", 90),  # Unity富文本标签
            "item_links": (r"\[item:.*?\]", 80),  # [item:sword_01]
            "npc_links": (r"\[npc:.*?\]", 80),    # [npc:merchant_01]
            "quest_links": (r"\[quest:.*?\]", 80), # [quest:main_01]
            "achievement_links": (r"\[achievement:.*?\]", 80), # [achievement:first_kill]
            "game_icons": (r"\[icon:.*?\]", 80),  # [icon:item_sword]
            "game_commands": (r"\/[a-zA-Z]+", 80), # /command
            
            # 格式化标签（中优先级）
            "percentage_vars": (r"%%[^%]*%%", 70),   # %%variable%%
            "format_specifiers": (r"%[\d\.]*[sdfeEgGxXoc]", 70),  # %s, %d, %.2f等
            "color_codes": (r"#[0-9a-fA-F]{6}", 70), # #FF0000
            
            # 通用标签（低优先级）
            "html_tags": (r"<[^>]+>", 60),        # <tag>
            "brackets": (r"\[.*?\]", 50),         # [text]
            "parentheses": (r"\(.*?\)", 50),      # (text)
            "quotes": (r"['\"].*?['\"]", 50),     # 'text' or "text"
            
            # 特殊格式（更低优先级）
            "currency_symbols": (r"[¥$€£₽₩₴₸₺₼₾₿]", 40), # 货币符号
            "number_format": (r"\d+[,\.]\d+", 40), # 数字格式 1,234.56
            "time_format": (r"\d{1,2}:\d{2}(:\d{2})?", 40), # 时间格式 12:34:56
            "date_format": (r"\d{4}-\d{2}-\d{2}", 40), # 日期格式 2024-01-01
            
            # 特殊字符（最低优先级）
            "special_chars": (r"[<>{}[\]()%$#@!&*+=|\\/]", 30),  # 特殊字符
        }
        
        # 编译正则表达式以提高性能
        self.compiled_patterns = {
            name: (re.compile(pattern, re.DOTALL), priority)
            for name, (pattern, priority) in self.patterns.items()
        }
        
        # 定义标签类型映射
        self.tag_type_map = {
            "brace_variables": "variable",
            "unity_rich_text": "rich_text",
            "item_links": "item",
            "npc_links": "npc",
            "quest_links": "quest",
            "achievement_links": "achievement",
            "game_icons": "icon",
            "game_commands": "command",
            "percentage_vars": "variable",
            "format_specifiers": "format",
            "color_codes": "color",
            "html_tags": "html",
            "brackets": "bracket",
            "parentheses": "parenthesis",
            "quotes": "quote",
            "currency_symbols": "currency",
            "number_format": "number",
            "time_format": "time",
            "date_format": "date",
            "special_chars": "special"
        }
        
        # 定义标签优先级阈值
        self.priority_thresholds = {
            'high': 80,  # 高优先级标签阈值
            'medium': 60,  # 中优先级标签阈值
            'low': 40,  # 低优先级标签阈值
        }
    
    def _find_non_overlapping_tags(self, text: str) -> List[TagInfo]:
        """
        查找文本中所有不重叠的标签，优先保留优先级高的标签
        
        Args:
            text: 需要处理的文本
            
        Returns:
            List[TagInfo]: 不重叠的标签列表，按起始位置排序
        """
        all_tags = []
        
        # 收集所有匹配的标签
        for pattern_name, (pattern, priority) in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                tag = match.group(0)
                all_tags.append(TagInfo(
                    original_tag=tag,
                    placeholder="",  # 占位符稍后生成
                    start_pos=match.start(),
                    end_pos=match.end(),
                    pattern_name=pattern_name,
                    priority=priority
                ))
        
        # 按优先级和位置排序
        all_tags.sort(key=lambda x: (-x.priority, x.start_pos))
        
        # 选择不重叠的标签
        non_overlapping = []
        used_ranges = set()
        
        for tag in all_tags:
            # 检查是否与已选标签重叠
            overlap = False
            for start, end in used_ranges:
                if (tag.start_pos < end and tag.end_pos > start):
                    overlap = True
                    break
            
            if not overlap:
                non_overlapping.append(tag)
                used_ranges.add((tag.start_pos, tag.end_pos))
        
        # 按位置排序
        non_overlapping.sort(key=lambda x: x.start_pos)
        
        # 生成占位符
        for i, tag in enumerate(non_overlapping):
            tag.placeholder = f"__TAG{i}__"
        
        return non_overlapping
    
    def protect_tags(self, text: str, custom_patterns: Optional[Dict[str, Tuple[str, int]]] = None) -> Tuple[str, Dict[str, TagInfo]]:
        """
        保护文本中的标签，将其替换为占位符
        
        Args:
            text: 需要处理的文本
            custom_patterns: 自定义的标签模式字典，格式为 {pattern_name: (regex_pattern, priority)}
            
        Returns:
            Tuple[str, Dict[str, TagInfo]]: (处理后的文本, 标签信息映射)
        """
        if not text:
            return text, {}
            
        try:
            # 合并默认模式和自定义模式
            patterns = self.patterns.copy()
            if custom_patterns:
                patterns.update(custom_patterns)
                
            # 编译自定义模式
            compiled_patterns = self.compiled_patterns.copy()
            for name, (pattern, priority) in custom_patterns.items() if custom_patterns else {}:
                try:
                    compiled_patterns[name] = (re.compile(pattern, re.DOTALL), priority)
                except re.error as e:
                    logger.error(f"Error compiling pattern '{name}': {str(e)}")
                    continue
            
            # 查找不重叠的标签
            tags = self._find_non_overlapping_tags(text)
            
            # 创建标签映射
            tag_map = {tag.placeholder: tag for tag in tags}
            
            # 替换标签为占位符（从后向前替换，避免位置偏移）
            protected_text = text
            for tag in sorted(tags, key=lambda x: x.start_pos, reverse=True):
                protected_text = protected_text[:tag.start_pos] + tag.placeholder + protected_text[tag.end_pos:]
            
            # 记录处理结果
            if tags:
                logger.info(f"Protected {len(tags)} tags in text. Patterns matched: {set(tag.pattern_name for tag in tags)}")
                logger.debug(f"Tag map: {tag_map}")
            
            return protected_text, tag_map
            
        except Exception as e:
            logger.error(f"Error in protect_tags: {str(e)}")
            return text, {}
    
    def restore_tags(self, text: str, tag_map: Dict[str, TagInfo]) -> str:
        """
        恢复文本中的标签，将占位符替换回原始标签
        
        Args:
            text: 需要恢复标签的文本
            tag_map: 标签信息映射
            
        Returns:
            str: 恢复标签后的文本
        """
        if not text or not tag_map:
            return text
            
        try:
            restored_text = text
            restored_count = 0
            missing_placeholders = set()
            
            # 按占位符编号顺序恢复
            sorted_placeholders = sorted(tag_map.keys(), 
                                      key=lambda x: int(x.strip('__TAG').strip('__')))
            
            # 检查所有占位符是否都存在
            for placeholder in sorted_placeholders:
                if placeholder not in text:
                    missing_placeholders.add(placeholder)
            
            if missing_placeholders:
                logger.warning(f"Missing placeholders in text: {missing_placeholders}")
            
            # 替换占位符
            for placeholder in sorted_placeholders:
                if placeholder in restored_text:
                    restored_text = restored_text.replace(placeholder, tag_map[placeholder].original_tag)
                    restored_count += 1
            
            # 记录处理结果
            if restored_count > 0:
                logger.info(f"Restored {restored_count} tags in text")
            if len(missing_placeholders) > 0:
                logger.warning(f"Failed to restore {len(missing_placeholders)} tags")
            
            return restored_text
            
        except Exception as e:
            logger.error(f"Error in restore_tags: {str(e)}")
            return text
    
    def validate_patterns(self, patterns: Dict[str, Tuple[str, int]]) -> List[str]:
        """
        验证正则表达式模式的有效性
        
        Args:
            patterns: 需要验证的模式字典，格式为 {pattern_name: (regex_pattern, priority)}
            
        Returns:
            List[str]: 无效的模式名称列表
        """
        invalid_patterns = []
        for name, (pattern, priority) in patterns.items():
            try:
                re.compile(pattern)
            except re.error:
                invalid_patterns.append(name)
        return invalid_patterns
    
    def get_pattern_description(self, pattern_name: str) -> Optional[str]:
        """
        获取模式描述
        
        Args:
            pattern_name: 模式名称
            
        Returns:
            Optional[str]: 模式描述
        """
        descriptions = {
            "brace_variables": "匹配花括号中的变量，如 {$playerName}",
            "html_tags": "匹配HTML标签，如 <b> 或 <color=red>",
            "unity_rich_text": "匹配Unity富文本标签，如 <b>, <i>, <color=red>, <size=20>",
            "percentage_vars": "匹配百分号包围的变量，如 %%token%%",
            "format_specifiers": "匹配格式化说明符，如 %s, %d, %.2f",
            "brackets": "匹配方括号中的文本，如 [text]",
            "parentheses": "匹配圆括号中的文本，如 (text)",
            "quotes": "匹配引号中的文本，如 'text' 或 \"text\"",
            "special_chars": "匹配特殊字符，如 <, >, {, }, [, ], (, ), %, $, #, @, !, &, *, +, =, |, \\, /",
            "game_icons": "匹配游戏图标标签，如 [icon:item_sword]",
            "game_commands": "匹配游戏命令，如 /command",
            "color_codes": "匹配颜色代码，如 #FF0000",
            "item_links": "匹配物品链接，如 [item:sword_01]",
            "npc_links": "匹配NPC链接，如 [npc:merchant_01]",
            "quest_links": "匹配任务链接，如 [quest:main_01]",
            "achievement_links": "匹配成就链接，如 [achievement:first_kill]",
            "currency_symbols": "匹配货币符号，如 ¥, $, €, £, ₽, ₩, ₴, ₸, ₺, ₼, ₾, ₿",
            "number_format": "匹配数字格式，如 1,234.56",
            "time_format": "匹配时间格式，如 12:34:56",
            "date_format": "匹配日期格式，如 2024-01-01"
        }
        return descriptions.get(pattern_name)
    
    def extract_tags(self, text: str) -> list:
        """
        提取文本中的所有标签（包括花括号、方括号、尖括号等）。
        返回标签字符串列表，顺序与出现顺序一致。
        """
        if not text:
            return []
            
        tags = []
        # 记录已处理的位置，避免重复匹配
        processed_positions = set()
        
        # 1. 首先处理游戏特定标签（高优先级）
        game_tag_patterns = {
            'brace_variables': r'{\$.*?}',  # {$variable}
            'item_links': r'\[item:.*?\]',  # [item:sword_01]
            'npc_links': r'\[npc:.*?\]',    # [npc:merchant_01]
            'quest_links': r'\[quest:.*?\]', # [quest:main_01]
            'achievement_links': r'\[achievement:.*?\]', # [achievement:first_kill]
            'game_icons': r'\[icon:.*?\]',  # [icon:item_sword]
            'game_commands': r'\/[a-zA-Z]+', # /command
        }
        
        for pattern_name, pattern in game_tag_patterns.items():
            for match in re.finditer(pattern, text):
                start, end = match.span()
                # 检查是否与已处理的标签重叠
                if any(start < p_end and end > p_start for p_start, p_end in processed_positions):
                    continue
                tag = match.group(0)
                tags.append(tag)
                processed_positions.add((start, end))
        
        # 2. 处理Unity富文本标签
        unity_tags = []
        for match in re.finditer(r'<([^>]+)>', text):
            start, end = match.span()
            # 检查是否与已处理的标签重叠
            if any(start < p_end and end > p_start for p_start, p_end in processed_positions):
                continue
            tag = match.group(0)
            # 检查是否是闭合标签
            if tag.startswith('</'):
                # 如果是闭合标签，检查是否有对应的开始标签
                open_tag = tag.replace('</', '<')
                if open_tag in unity_tags:
                    tags.append(tag)
                    processed_positions.add((start, end))
            else:
                unity_tags.append(tag)
                tags.append(tag)
                processed_positions.add((start, end))
        
        # 3. 处理格式化标签（中优先级）
        format_patterns = {
            'percentage_vars': r'%%[^%]*%%',   # %%variable%%
            'format_specifiers': r'%[\d\.]*[sdfeEgGxXoc]',  # %s, %d, %.2f等
            'color_codes': r'#[0-9a-fA-F]{6}', # #FF0000
        }
        
        for pattern_name, pattern in format_patterns.items():
            for match in re.finditer(pattern, text):
                start, end = match.span()
                # 检查是否与已处理的标签重叠
                if any(start < p_end and end > p_start for p_start, p_end in processed_positions):
                    continue
                tag = match.group(0)
                tags.append(tag)
                processed_positions.add((start, end))
        
        # 4. 处理通用标签（低优先级）
        general_patterns = {
            'html_tags': r'<[^>]+>',        # <tag>
            'brackets': r'\[.*?\]',         # [text]
            'parentheses': r'\(.*?\)',      # (text)
            'quotes': r'[\'"].*?[\'"]',     # 'text' or "text"
        }
        
        for pattern_name, pattern in general_patterns.items():
            for match in re.finditer(pattern, text):
                start, end = match.span()
                # 检查是否与已处理的标签重叠
                if any(start < p_end and end > p_start for p_start, p_end in processed_positions):
                    continue
                tag = match.group(0)
                tags.append(tag)
                processed_positions.add((start, end))
        
        # 按在原文中的顺序排序
        tags.sort(key=lambda x: text.find(x))
        return tags

    def _evaluate_tag_preservation(self, source_text: str, translated_text: str) -> Tuple[float, List[str]]:
        """评估标签保留情况"""
        issues = []
        
        # 提取源文本中的标签
        source_tags = self.extract_tags(source_text)
        translated_tags = self.extract_tags(translated_text)
        
        # 检查标签是否完整保留
        if len(source_tags) != len(translated_tags):
            issues.append(f"标签数量不匹配: 源文本 {len(source_tags)} 个, 翻译后 {len(translated_tags)} 个")
            return 0.0, issues
        
        # 检查标签内容是否一致
        for src_tag, trans_tag in zip(source_tags, translated_tags):
            # 对于游戏标签，只比较标签类型和ID
            if re.match(r'\[(item|npc|quest|location|achievement):.*?\]', src_tag):
                src_type = re.match(r'\[(.*?):', src_tag).group(1)
                trans_type = re.match(r'\[(.*?):', trans_tag).group(1)
                if src_type != trans_type:
                    issues.append(f"标签类型不一致: {src_tag} -> {trans_tag}")
            # 对于Unity富文本标签，检查标签类型和属性
            elif re.match(r'<\/?(b|i|size|color|material|quad|sprite|link|nobr|page|indent|align|mark|mspace|width|style|gradient|cspace|font|voffset|line-height|pos|space|noparse|uppercase|lowercase|smallcaps|sup|sub)(=[^>]*)?>', src_tag):
                src_type = re.match(r'<\/?([a-zA-Z]+)', src_tag).group(1)
                trans_type = re.match(r'<\/?([a-zA-Z]+)', trans_tag).group(1)
                if src_type != trans_type:
                    issues.append(f"标签类型不一致: {src_tag} -> {trans_tag}")
            # 对于其他标签，严格比较
            else:
                if src_tag != trans_tag:
                    issues.append(f"标签内容不一致: {src_tag} -> {trans_tag}")
        
        # 计算得分：如果没有问题，得分为100；每有一个问题扣20分
        score = 100.0 if not issues else max(0.0, 100.0 - (len(issues) * 20.0))
        return score, issues 