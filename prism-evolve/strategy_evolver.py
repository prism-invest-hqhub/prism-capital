"""
棱镜策略迭代引擎 v1.0
参数网格搜索 + 策略对比优化
"""
import sys
sys.path.insert(0, "/app/data/所有对话/主对话/prism-data")
sys.path.insert(0, "/app/data/所有对话/主对话/prism-backtest")
sys.path.insert(0, "/app/data/所有对话/主对话/prism-data")

from prism_db import init_db, save_backtest, get_conn
from backtest_engine import BacktestEngine
from datetime import datetime, timedelta
import itertools
import json
from typing import List, Dict, Tuple, Optional


class StrategyEvolver:
    """策略迭代优化引擎"""
    
    def __init__(self):
        self.db_path = "/app/data/所有对话/主对话/prism-data/prism.db"
        self.backtest_engine = BacktestEngine()
        init_db()
    
    def generate_param_grid(
        self,
        double_low_range: Tuple[int, int, int] = (100, 130, 5),  # start, end, step
        max_positions: Tuple[int, int, int] = (3, 10, 1),  # start, end, step
        rebalance_days: Tuple[int, int, int] = (5, 30, 5),  # start, end, step
        stop_loss_range: Tuple[float, float, float] = (5, 15, 2.5),  # 止损百分比范围 (正值)
        take_profit_range: Tuple[float, float, float] = (10, 30, 5),  # 止盈百分比范围
    ) -> List[Dict]:
        """
        生成参数网格
        
        Args:
            double_low_range: 双低值范围 (起始, 结束, 步长)
            max_positions: 最大持仓数范围
            rebalance_days: 调仓周期范围
            stop_loss_range: 止损百分比范围 (正值，如5表示-5%)
            take_profit_range: 止盈百分比范围
            
        Returns:
            list: 参数组合列表
        """
        grid = []
        
        # 生成各参数范围
        double_low_values = list(range(
            double_low_range[0],
            double_low_range[1] + 1,
            double_low_range[2]
        ))
        max_pos_values = list(range(
            max_positions[0],
            max_positions[1] + 1,
            max_positions[2]
        ))
        rebalance_values = list(range(
            rebalance_days[0],
            rebalance_days[1] + 1,
            rebalance_days[2]
        ))
        stop_loss_values = [round(x * 0.01, 3) for x in range(
            int(stop_loss_range[0] * 100),
            int(stop_loss_range[1] * 100) + 1,
            int(stop_loss_range[2] * 100)
        )]
        take_profit_values = [round(x * 0.01, 3) for x in range(
            int(take_profit_range[0]),
            int(take_profit_range[1]) + 1,
            int(take_profit_range[2])
        )]
        
        # 组合所有参数
        param_combinations = list(itertools.product(
            double_low_values,
            max_pos_values,
            rebalance_values,
            stop_loss_values,
            take_profit_values
        ))
        
        for combo in param_combinations:
            grid.append({
                "double_low_threshold": combo[0],
                "max_positions": combo[1],
                "rebalance_days": combo[2],
                "stop_loss": -combo[3],  # 转为负数
                "take_profit": combo[4],
            })
        
        return grid
    
    def run_single_backtest(self, params: Dict, days: int = 180) -> Dict:
        """
        运行单次回测
        
        Args:
            params: 策略参数
            days: 回测天数
            
        Returns:
            dict: 回测结果
        """
        try:
            result = self.backtest_engine.run_backtest(
                days=days,
                strategy="double_low",
                double_low_threshold=params.get("double_low_threshold", 110),
                max_positions=params.get("max_positions", 5),
                rebalance_days=params.get("rebalance_days", 10),
                stop_loss=params.get("stop_loss", -0.08),
                take_profit=params.get("take_profit", 0.20),
            )
            return result
        except Exception as e:
            return {
                "error": str(e),
                "total_return": 0,
                "annual_return": 0,
                "max_drawdown": 0,
                "sharpe": 0,
                "win_rate": 0,
                "trade_count": 0,
            }
    
    def compare_strategies(
        self,
        param_list: List[Dict],
        days: int = 180,
        show_progress: bool = True
    ) -> List[Dict]:
        """
        对比多组参数的回测结果
        
        Args:
            param_list: 参数组合列表
            days: 回测天数
            show_progress: 是否显示进度
            
        Returns:
            list: 带参数的回测结果列表
        """
        results = []
        total = len(param_list)
        
        for i, params in enumerate(param_list):
            if show_progress:
                print(f"  进度: {i+1}/{total} ({100*(i+1)/total:.1f}%) - 测试参数: {params}")
            
            result = self.run_single_backtest(params, days)
            result["params"] = params
            results.append(result)
            
            # 保存到数据库
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            save_backtest(
                strategy_name="double_low",
                params=params,
                start_date=start_date,
                end_date=end_date,
                results=result
            )
        
        return results
    
    def rank_strategies(
        self,
        results: List[Dict],
        sort_by: str = "sharpe",
        top_n: int = 10
    ) -> List[Dict]:
        """
        策略排名
        
        Args:
            results: 回测结果列表
            sort_by: 排序字段 (sharpe/annual_return/max_drawdown/win_rate)
            top_n: 返回前N名
            
        Returns:
            list: 排序后的策略列表
        """
        if not results:
            return []
        
        # 过滤无效结果
        valid_results = [r for r in results if "error" not in r]
        
        # 定义排序键
        sort_keys = {
            "sharpe": lambda r: r.get("sharpe", 0),
            "annual_return": lambda r: r.get("annual_return", 0),
            "total_return": lambda r: r.get("total_return", 0),
            "max_drawdown": lambda r: -abs(r.get("max_drawdown", 0)),  # 越小越好
            "win_rate": lambda r: r.get("win_rate", 0),
            "composite": lambda r: (
                r.get("sharpe", 0) * 0.3 +
                r.get("annual_return", 0) * 0.3 +
                (-abs(r.get("max_drawdown", 0))) * 0.2 +
                r.get("win_rate", 0) * 0.2
            ),
        }
        
        sort_key = sort_keys.get(sort_by, sort_keys["sharpe"])
        
        # 排序
        sorted_results = sorted(valid_results, key=sort_key, reverse=True)
        
        # 添加排名
        for i, r in enumerate(sorted_results[:top_n]):
            r["rank"] = i + 1
        
        return sorted_results[:top_n]
    
    def optimize(
        self,
        days: int = 180,
        max_combinations: int = 100,
        quick_mode: bool = True
    ) -> Dict:
        """
        自动优化找最优参数
        
        Args:
            days: 回测天数
            max_combinations: 最大测试组合数
            quick_mode: 快速模式，使用较少参数组合
            
        Returns:
            dict: 最优参数和结果
        """
        print(f"\n🔍 开始策略优化...")
        print(f"   回测天数: {days}")
        print(f"   最大组合数: {max_combinations}")
        print(f"   快速模式: {'是' if quick_mode else '否'}")
        
        if quick_mode:
            # 快速模式：使用大步长
            param_grid = self.generate_param_grid(
                double_low_range=(100, 125, 15),
                max_positions=(3, 8, 3),
                rebalance_days=(5, 20, 10),
                stop_loss_range=(5, 12, 7),
                take_profit_range=(15, 30, 15),
            )
        else:
            # 完整模式
            param_grid = self.generate_param_grid(
                double_low_range=(100, 130, 5),
                max_positions=(3, 10, 1),
                rebalance_days=(5, 30, 5),
                stop_loss_range=(5, 15, 2.5),
                take_profit_range=(10, 30, 5),
            )
        
        # 限制组合数量
        if len(param_grid) > max_combinations:
            param_grid = param_grid[:max_combinations]
        
        print(f"   实际测试组合数: {len(param_grid)}")
        
        # 运行对比
        results = self.compare_strategies(param_grid, days, show_progress=True)
        
        # 综合排名
        ranked = self.rank_strategies(results, sort_by="composite", top_n=5)
        
        # 最优策略
        best = ranked[0] if ranked else None
        
        print(f"\n✅ 优化完成!")
        print(f"\n🏆 最优参数组合:")
        if best:
            print(f"   双低阈值: {best['params']['double_low_threshold']}")
            print(f"   最大持仓: {best['params']['max_positions']}")
            print(f"   调仓周期: {best['params']['rebalance_days']}天")
            print(f"   止损比例: {best['params']['stop_loss']*100:.1f}%")
            print(f"   止盈比例: {best['params']['take_profit']*100:.1f}%")
            print(f"\n📊 最优结果:")
            print(f"   总收益: {best['total_return']*100:.2f}%")
            print(f"   年化收益: {best['annual_return']*100:.2f}%")
            print(f"   最大回撤: {best['max_drawdown']*100:.2f}%")
            print(f"   夏普比率: {best['sharpe']:.2f}")
            print(f"   胜率: {best['win_rate']*100:.1f}%")
        
        # 返回前5名
        return {
            "best_params": best["params"] if best else None,
            "best_results": best if best else None,
            "top_5_strategies": ranked,
            "total_tested": len(results),
        }
    
    def get_evolution_history(self, limit: int = 50) -> List[Dict]:
        """获取历史优化记录"""
        conn = get_conn()
        rows = conn.execute("""
            SELECT * FROM backtest_results 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        
        results = []
        for row in rows:
            r = dict(row)
            # 解析JSON字段
            if r.get("params"):
                r["params"] = json.loads(r["params"])
            if r.get("details"):
                r["details"] = json.loads(r["details"])
            results.append(r)
        
        return results
    
    def suggest_improvements(self, results: List[Dict]) -> List[str]:
        """
        基于回测结果给出优化建议
        
        Args:
            results: 回测结果列表
            
        Returns:
            list: 优化建议
        """
        suggestions = []
        
        if not results:
            return ["暂无数据，建议先运行回测"]
        
        # 分析平均表现
        valid_results = [r for r in results if r.get("annual_return") is not None]
        if not valid_results:
            return ["暂无有效回测数据"]
        
        avg_return = sum(r.get("annual_return", 0) or 0 for r in valid_results) / len(valid_results)
        avg_drawdown = sum(abs(r.get("max_drawdown", 0) or 0) for r in valid_results) / len(valid_results)
        avg_sharpe = sum(r.get("sharpe", 0) or 0 for r in valid_results) / len(valid_results)
        
        # 分析最优参数趋势
        best_by_return = max(valid_results, key=lambda r: r.get("annual_return", 0) or 0)
        best_by_sharpe = max(valid_results, key=lambda r: r.get("sharpe", 0) or 0)
        
        # 生成建议
        if avg_return < 0:
            suggestions.append("⚠️ 平均收益为负，建议提高双低阈值或延长调仓周期")
        
        if avg_drawdown > 0.15:
            suggestions.append("⚠️ 平均回撤较大，建议收紧止损比例")
        
        if avg_sharpe < 0.5:
            suggestions.append("⚠️ 夏普比率偏低，建议优化仓位管理")
        
        # 参数趋势建议
        best_dl = best_by_return.get("params", {}).get("double_low_threshold", 110)
        if best_dl < 110:
            suggestions.append("📈 低双低阈值表现更好，可考虑进一步降低阈值")
        elif best_dl > 115:
            suggestions.append("📈 较高双低阈值表现更好，说明当前市场偏防守")
        
        best_rbd = best_by_return.get("params", {}).get("rebalance_days", 10)
        if best_rbd < 10:
            suggestions.append("📈 短周期调仓表现更好，可考虑更频繁的换仓")
        elif best_rbd > 15:
            suggestions.append("📈 长周期调仓表现更好，市场趋势较稳定")
        
        if not suggestions:
            suggestions.append("✅ 当前参数组合表现良好，建议持续监控")
        
        return suggestions


def quick_test():
    """快速测试模式"""
    print("\n" + "=" * 60)
    print("棱镜策略迭代引擎 v1.0 - 快速测试")
    print("=" * 60)
    
    evolver = StrategyEvolver()
    
    # 1. 生成参数网格
    print("\n📊 生成测试参数网格 (快速模式)...")
    grid = evolver.generate_param_grid(
        double_low_range=(100, 120, 10),
        max_positions=(3, 6, 2),
        rebalance_days=(5, 15, 5),
        stop_loss_range=(5, 10, 5),
        take_profit_range=(15, 25, 10),
    )
    print(f"   生成了 {len(grid)} 组参数组合")
    
    # 显示前5组
    print("\n   前5组参数:")
    for i, p in enumerate(grid[:5]):
        print(f"   [{i+1}] 双低={p['double_low_threshold']}, 持仓={p['max_positions']}, "
              f"调仓={p['rebalance_days']}天, 止损={p['stop_loss']*100:.0f}%, "
              f"止盈={p['take_profit']*100:.0f}%")
    
    # 2. 测试单次回测
    print("\n📈 测试单次回测...")
    test_params = {
        "double_low_threshold": 110,
        "max_positions": 5,
        "rebalance_days": 10,
        "stop_loss": -0.08,
        "take_profit": 0.20,
    }
    result = evolver.run_single_backtest(test_params, days=60)
    print(f"   总收益: {result.get('total_return', 0)*100:.2f}%")
    print(f"   年化: {result.get('annual_return', 0)*100:.2f}%")
    print(f"   最大回撤: {result.get('max_drawdown', 0)*100:.2f}%")
    print(f"   夏普: {result.get('sharpe', 0):.2f}")
    print(f"   交易次数: {result.get('trade_count', 0)}")
    
    # 3. 历史优化建议
    print("\n💡 优化建议:")
    history = evolver.get_evolution_history(limit=10)
    if history:
        suggestions = evolver.suggest_improvements(history)
        for s in suggestions:
            print(f"   {s}")
    else:
        print("   暂无历史数据")
    
    print("\n" + "=" * 60)
    print("✅ 策略迭代引擎验证完成!")
    print("=" * 60)


if __name__ == "__main__":
    quick_test()
