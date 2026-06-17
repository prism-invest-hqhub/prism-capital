"""
棱镜情感分析引擎 v1.0
从财经新闻中提取情感信号和交易信号
"""
import sys
sys.path.insert(0, "/app/data/所有对话/主对话/prism-data")
from prism_db import init_db, save_news, save_signal, get_conn
from datetime import datetime, timedelta
import json
import random

# 情感词典：关键词 -> 情感极性权重
POSITIVE_KEYWORDS = {
    # 强烈利好
    "下修": 0.6, "提议下修": 0.7, "转股价下修": 0.6,
    "大幅下修": 0.8, "下修到底": 0.9,
    "业绩增长": 0.5, "净利润增长": 0.5, "营收增长": 0.4,
    "超预期": 0.6, "大超预期": 0.8,
    "回购": 0.4, "增持": 0.5, "大股东增持": 0.6,
    "分红": 0.3, "高分红": 0.4,
    "扭亏": 0.7, "大幅扭亏": 0.9,
    "中标": 0.5, "重大订单": 0.6,
    "突破": 0.4, "技术突破": 0.6,
    "合作": 0.3, "战略合作": 0.5,
    "政策支持": 0.5, "利好": 0.4,
}

NEGATIVE_KEYWORDS = {
    # 强烈利空
    "强赎": -0.8, "强制赎回": -0.8, "公告强赎": -0.9,
    "暂停强赎": -0.3, "取消强赎": 0.2,
    "下调": -0.5, "评级下调": -0.6, "展望下调": -0.4,
    "业绩下降": -0.5, "净利润下降": -0.5, "亏损": -0.6,
    "商誉减值": -0.7, "资产减值": -0.6,
    "减持": -0.4, "大股东减持": -0.5,
    "诉讼": -0.4, "仲裁": -0.4, "处罚": -0.6,
    "监管函": -0.5, "警示函": -0.5,
    "立案调查": -0.8, "被调查": -0.7,
    "债务风险": -0.7, "违约": -0.8,
    "ST": -0.6, "*ST": -0.8, "退市风险": -0.9,
    "业绩雷": -0.8, "黑天鹅": -0.9,
    "利空": -0.5, "风险提示": -0.4,
}

# 中性/观察关键词
WATCH_KEYWORDS = {
    "回售": 0.0, "提前回售": 0.0, "回售登记": 0.0,
    "到期": 0.0, "到期赎回": 0.0,
    "停牌": 0.0, "暂停交易": 0.0,
    "转债发行": 0.0, "新债上市": 0.0,
    "股东大会": 0.0, "表决": 0.0,
    "转股": 0.0, "转股进度": 0.0,
    "不下修": -0.1, "暂不下修": -0.1,
    "不下修承诺": -0.1,
}


class SentimentEngine:
    """情感分析引擎"""
    
    def __init__(self):
        self.db_path = "/app/data/所有对话/主对话/prism-data/prism.db"
        init_db()
    
    def analyze_sentiment(self, text: str) -> float:
        """
        分析文本情感，返回 -1 到 1 之间的情感分数
        
        Args:
            text: 新闻标题或内容
            
        Returns:
            float: 情感分数 (-1 到 1)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        sentiment_score = 0.0
        matched_keywords = []
        
        # 检测正面关键词
        for keyword, weight in POSITIVE_KEYWORDS.items():
            if keyword in text_lower:
                sentiment_score += weight
                matched_keywords.append(("positive", keyword, weight))
        
        # 检测负面关键词
        for keyword, weight in NEGATIVE_KEYWORDS.items():
            if keyword in text_lower:
                sentiment_score += weight
                matched_keywords.append(("negative", keyword, weight))
        
        # 检测观察关键词
        for keyword, weight in WATCH_KEYWORDS.items():
            if keyword in text_lower:
                sentiment_score += weight
                matched_keywords.append(("watch", keyword, weight))
        
        # 归一化到 [-1, 1]
        if len(matched_keywords) > 0:
            avg_score = sentiment_score / len(matched_keywords)
            # 根据匹配数量调整
            boost = min(len(matched_keywords) * 0.05, 0.2)
            sentiment_score = max(-1.0, min(1.0, sentiment_score + boost))
        else:
            sentiment_score = 0.0
        
        return round(sentiment_score, 4)
    
    def extract_signals(self, news_list: list) -> list:
        """
        从新闻列表中提取交易信号
        
        Args:
            news_list: 新闻列表，每个元素包含 title, sentiment, related_codes 等
            
        Returns:
            list: 交易信号列表
        """
        signals = []
        
        for news in news_list:
            title = news.get("title", "")
            sentiment = news.get("sentiment", self.analyze_sentiment(title))
            codes = news.get("related_codes", [])
            source = news.get("source", "")
            
            # 根据关键词类型生成交易信号
            signal = None
            signal_type = None
            action = None
            
            # 下修信号 -> BUY
            if "下修" in title and sentiment > 0:
                signal_type = "下修"
                action = "BUY"
                reason = f"转股价下修，转债价格有望提升"
            
            # 强赎信号 -> SELL
            elif "强赎" in title and sentiment < 0:
                signal_type = "强赎"
                action = "SELL"
                reason = f"转债面临强制赎回风险，建议卖出"
            
            # 回售信号 -> WATCH
            elif "回售" in title:
                signal_type = "回售"
                action = "WATCH"
                reason = f"触发回售条款，关注持仓风险"
            
            # 下调评级 -> SELL
            elif "下调" in title and "评级" in title:
                signal_type = "评级下调"
                action = "SELL"
                reason = f"评级被下调，基本面可能恶化"
            
            # ST风险 -> SELL
            elif any(st in title for st in ["ST", "*ST", "退市风险"]):
                signal_type = "ST风险"
                action = "SELL"
                reason = f"存在退市风险，建议卖出"
            
            # 超预期业绩 -> BUY
            elif "超预期" in title and sentiment > 0:
                signal_type = "业绩超预期"
                action = "BUY"
                reason = f"业绩超预期，正股上涨概率大"
            
            # 不下修 -> WATCH
            elif "不下修" in title:
                signal_type = "不下修"
                action = "WATCH"
                reason = f"公司承诺不下修，关注后续"
            
            if signal_type and codes:
                signals.append({
                    "signal_type": signal_type,
                    "action": action,
                    "codes": codes,
                    "title": title,
                    "sentiment": sentiment,
                    "reason": reason,
                    "source": source,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
                # 保存到数据库
                for code in codes:
                    save_signal(
                        code=code,
                        name="",
                        signal_type=signal_type,
                        strategy="sentiment",
                        price=None,
                        reason=reason,
                        confidence=abs(sentiment)
                    )
        
        return signals
    
    def batch_analyze(self, news_list: list) -> list:
        """
        批量分析新闻情感
        
        Args:
            news_list: 新闻列表
            
        Returns:
            list: 处理后的新闻列表，包含情感分数和信号
        """
        results = []
        
        for news in news_list:
            title = news.get("title", "")
            content = news.get("content", "")
            source = news.get("source", "")
            url = news.get("url", "")
            related_codes = news.get("related_codes", [])
            published_at = news.get("published_at", datetime.now().strftime("%Y-%m-%d"))
            
            # 分析标题和内容的综合情感
            title_sentiment = self.analyze_sentiment(title)
            content_sentiment = self.analyze_sentiment(content) if content else 0.0
            overall_sentiment = (title_sentiment * 0.7 + content_sentiment * 0.3)
            
            # 情感分类
            if overall_sentiment > 0.3:
                sentiment_label = "positive"
            elif overall_sentiment < -0.3:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"
            
            # 提取关键词
            keywords = self._extract_keywords(title + " " + content)
            
            # 保存到数据库
            try:
                save_news(
                    title=title,
                    source=source,
                    url=url,
                    sentiment=overall_sentiment,
                    keywords=keywords,
                    related_codes=related_codes,
                    published_at=published_at
                )
            except Exception as e:
                print(f"保存新闻失败: {e}")
            
            results.append({
                "title": title,
                "sentiment": overall_sentiment,
                "sentiment_label": sentiment_label,
                "title_sentiment": title_sentiment,
                "content_sentiment": content_sentiment,
                "keywords": keywords,
                "related_codes": related_codes,
                "source": source,
                "published_at": published_at,
            })
        
        return results
    
    def _extract_keywords(self, text: str) -> list:
        """提取文本中的关键词"""
        all_keywords = {}
        for d in [POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS, WATCH_KEYWORDS]:
            for k in d.keys():
                if k in text.lower():
                    all_keywords[k] = d[k]
        
        # 按权重排序
        sorted_keywords = sorted(all_keywords.items(), key=lambda x: abs(x[1]), reverse=True)
        return [k for k, _ in sorted_keywords[:10]]
    
    def get_recent_signals(self, limit: int = 20) -> list:
        """获取最近的情感信号"""
        conn = get_conn()
        rows = conn.execute("""
            SELECT * FROM signals 
            WHERE strategy = 'sentiment'
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_sentiment_summary(self, days: int = 7) -> dict:
        """获取最近N天的情感摘要"""
        conn = get_conn()
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 获取情感统计
        stats = conn.execute("""
            SELECT 
                COUNT(*) as total,
                AVG(sentiment) as avg_sentiment,
                SUM(CASE WHEN sentiment > 0.3 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN sentiment < -0.3 THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN sentiment >= -0.3 AND sentiment <= 0.3 THEN 1 ELSE 0 END) as neutral
            FROM news 
            WHERE published_at >= ?
        """, (since,)).fetchone()
        
        # 获取最近情感分布
        recent = conn.execute("""
            SELECT title, sentiment, published_at 
            FROM news 
            ORDER BY published_at DESC 
            LIMIT 10
        """).fetchall()
        
        conn.close()
        
        return {
            "period_days": days,
            "total_news": stats["total"] or 0,
            "avg_sentiment": round(stats["avg_sentiment"] or 0, 4),
            "positive_count": stats["positive"] or 0,
            "negative_count": stats["negative"] or 0,
            "neutral_count": stats["neutral"] or 0,
            "recent_news": [dict(r) for r in recent],
            "overall_mood": self._sentiment_to_mood(stats["avg_sentiment"] or 0)
        }
    
    def _sentiment_to_mood(self, sentiment: float) -> str:
        """将情感分数转换为情绪描述"""
        if sentiment > 0.5:
            return "极度乐观"
        elif sentiment > 0.2:
            return "偏乐观"
        elif sentiment > -0.2:
            return "中性"
        elif sentiment > -0.5:
            return "偏悲观"
        else:
            return "极度悲观"


def generate_mock_news() -> list:
    """生成模拟新闻数据用于测试"""
    return [
        {
            "title": "某可转债公告转股价下修到底，转债价格有望提升",
            "source": "证券时报",
            "related_codes": ["113001", "127045"],
            "published_at": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "title": "紧急！某转债触发强赎条款，持有者需注意",
            "source": "Wind资讯",
            "related_codes": ["128095", "113050"],
            "published_at": (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d"),
        },
        {
            "title": "某公司发布回售公告，持有相关可转债的投资者需关注",
            "source": "上海证券报",
            "related_codes": ["113536"],
            "published_at": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d"),
        },
        {
            "title": "某券商下调某公司评级，警惕股价下跌风险",
            "source": "中金公司",
            "related_codes": ["600519"],
            "published_at": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        {
            "title": "业绩超预期！某科技公司净利润同比增长50%",
            "source": "财联社",
            "related_codes": ["300750"],
            "published_at": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        {
            "title": "某转债公司承诺6个月内不下修转股价",
            "source": "公司公告",
            "related_codes": ["113505"],
            "published_at": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        },
        {
            "title": "*ST某某公司面临退市风险警示",
            "source": "风险提示",
            "related_codes": ["127034"],
            "published_at": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        },
        {
            "title": "某可转债提议下修转股价，为促进转股",
            "source": "债券研究",
            "related_codes": ["128136", "127047"],
            "published_at": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        },
    ]


if __name__ == "__main__":
    print("=" * 60)
    print("棱镜情感分析引擎 v1.0 - 测试验证")
    print("=" * 60)
    
    # 初始化引擎
    engine = SentimentEngine()
    
    # 1. 测试情感分析
    print("\n📊 情感分析测试:")
    test_texts = [
        "某可转债公告转股价下修到底，转债价格有望提升",
        "紧急！某转债触发强赎条款，持有者需注意",
        "某公司发布回售公告，持有相关可转债的投资者需关注",
        "某券商下调某公司评级，警惕股价下跌风险",
        "业绩超预期！某科技公司净利润同比增长50%",
        "某转债公司承诺6个月内不下修转股价",
        "*ST某某公司面临退市风险警示",
    ]
    
    for text in test_texts:
        sentiment = engine.analyze_sentiment(text)
        label = "🟢正面" if sentiment > 0.2 else "🔴负面" if sentiment < -0.2 else "⚪中性"
        print(f"  {label} [{sentiment:+.2f}] {text[:30]}...")
    
    # 2. 批量分析模拟新闻
    print("\n📰 批量新闻分析:")
    mock_news = generate_mock_news()
    results = engine.batch_analyze(mock_news)
    
    for r in results:
        label = "🟢" if r["sentiment_label"] == "positive" else "🔴" if r["sentiment_label"] == "negative" else "⚪"
        print(f"  {label} [{r['sentiment']:+.2f}] {r['title'][:35]}...")
    
    # 3. 提取交易信号
    print("\n📈 提取交易信号:")
    signals = engine.extract_signals(mock_news)
    if signals:
        for s in signals:
            action_emoji = "🟢 BUY" if s["action"] == "BUY" else "🔴 SELL" if s["action"] == "SELL" else "⚪ WATCH"
            print(f"  {action_emoji} | {s['signal_type']} | {s['codes']} | {s['reason']}")
    else:
        print("  暂无明显交易信号")
    
    # 4. 情感摘要
    print("\n📋 情感摘要:")
    summary = engine.get_sentiment_summary(days=7)
    print(f"  统计周期: 最近{summary['period_days']}天")
    print(f"  新闻总数: {summary['total_news']}")
    print(f"  平均情感: {summary['avg_sentiment']:+.4f}")
    print(f"  正面新闻: {summary['positive_count']}条")
    print(f"  负面新闻: {summary['negative_count']}条")
    print(f"  中性新闻: {summary['neutral_count']}条")
    print(f"  市场情绪: {summary['overall_mood']}")
    
    print("\n" + "=" * 60)
    print("✅ 情感分析引擎验证完成!")
    print("=" * 60)
