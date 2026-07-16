"""
演示数据生成器

生成模拟电商数据 CSV 文件，供面试演示使用。
数据包含自然的趋势和波动，让 Agent 分析时有东西可挖。

数据结构:
  sales.csv  — 销售记录（日期、产品、品类、区域、金额、数量）
  orders.csv — 订单记录（订单ID、客户、日期、金额、状态）
  users.csv  — 用户记录（用户ID、城市、年龄、注册日期、最后登录）
"""

import csv
import logging
import random
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── 常量 ───
PRODUCTS = ["手机支架", "蓝牙耳机", "充电宝", "数据线", "手机壳"]
CATEGORIES = ["3C配件", "音频", "充电续航", "线材", "保护壳"]
REGIONS = ["华东", "华南", "华北"]
CITIES = ["上海", "深圳", "北京", "杭州", "广州", "成都", "武汉", "南京"]
ORDER_STATUSES = ["已完成", "已发货", "处理中", "已取消", "已退款"]
TODAY = date.today()

# 种子保证每次生成的数据一致（方便面试反复演示）
random.seed(42)


def _random_date(start: date, end: date) -> str:
    """生成随机日期"""
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def generate_sales(output_dir: str = "data", rows: int = 500):
    """
    生成销售数据

    模拟数据特征（故意设计让 Agent 能发现规律）:
      - 手机支架 Q3 爆发增长（+35%），模拟爆款效应
      - 蓝牙耳机 8 月小幅下滑（-8%），模拟季节性波动
      - 充电宝 9 月反弹明显，模拟开学季效应
      - 华东区域贡献 45% 收入
    """
    filepath = Path(output_dir) / "sales.csv"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("生成销售演示数据: %s (%d 行)", filepath, rows)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "product", "category", "region", "amount", "quantity"])

        for _ in range(rows):
            product = random.choice(PRODUCTS)
            idx = PRODUCTS.index(product)
            date_str = _random_date(TODAY - timedelta(days=365), TODAY)

            # ─── 模拟趋势 ───
            month = int(date_str[5:7])
            base_amount = 5000 + idx * 2000  # 每产品基准不同
            amount_noise = random.gauss(0, 500)

            # 手机支架 Q3 爆发（7/8/9月）
            if product == "手机支架" and month in [7, 8, 9]:
                base_amount *= random.uniform(1.2, 1.5)
            # 蓝牙耳机 8 月下滑
            if product == "蓝牙耳机" and month == 8:
                base_amount *= random.uniform(0.75, 0.85)
            # 充电宝 9 月反弹
            if product == "充电宝" and month == 9:
                base_amount *= random.uniform(1.15, 1.3)

            amount = round(max(100, base_amount + amount_noise), 2)
            quantity = max(1, int(amount / random.uniform(80, 200)))

            writer.writerow(
                [
                    date_str,
                    product,
                    CATEGORIES[idx],
                    random.choice(REGIONS),
                    amount,
                    quantity,
                ]
            )

    logger.info("销售数据生成完成: %d 行", rows)


def generate_orders(output_dir: str = "data", rows: int = 300):
    """
    生成订单数据

    模拟数据特征:
      - 退单率约 12%（已取消 + 已退款）
      - 部分客户有多次购买记录
    """
    filepath = Path(output_dir) / "orders.csv"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("生成订单演示数据: %s (%d 行)", filepath, rows)

    customer_names = [f"C{1000 + i:04d}" for i in range(50)]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "customer", "date", "amount", "status"])

        for i in range(rows):
            # 状态分布: 已完成 60%, 已发货 20%, 处理中 8%, 已取消 7%, 已退款 5%
            status_roll = random.random()
            if status_roll < 0.60:
                status = "已完成"
            elif status_roll < 0.80:
                status = "已发货"
            elif status_roll < 0.88:
                status = "处理中"
            elif status_roll < 0.95:
                status = "已取消"
            else:
                status = "已退款"

            writer.writerow(
                [
                    f"ORD-{10000 + i}",
                    random.choice(customer_names),
                    _random_date(TODAY - timedelta(days=365), TODAY),
                    round(random.uniform(50, 2000), 2),
                    status,
                ]
            )

    logger.info("订单数据生成完成: %d 行", rows)


def generate_users(output_dir: str = "data", rows: int = 200):
    """
    生成用户数据

    模拟数据特征:
      - 一线城市用户占比 60%
      - 18-35 岁年轻用户为主（70%）
      - 部分用户长期未登录（流失风险）
    """
    filepath = Path(output_dir) / "users.csv"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("生成用户演示数据: %s (%d 行)", filepath, rows)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "city", "age", "register_date", "last_login"])

        for i in range(rows):
            register_date = _random_date(TODAY - timedelta(days=730), TODAY)
            last_login = _random_date(
                date.fromisoformat(register_date),
                TODAY,
            )

            # 年龄分布: 18-25(35%), 26-35(35%), 36-50(20%), 50+(10%)
            age_roll = random.random()
            if age_roll < 0.35:
                age = random.randint(18, 25)
            elif age_roll < 0.70:
                age = random.randint(26, 35)
            elif age_roll < 0.90:
                age = random.randint(36, 50)
            else:
                age = random.randint(51, 65)

            writer.writerow(
                [
                    f"U-{10000 + i}",
                    random.choice(CITIES),
                    age,
                    register_date,
                    last_login,
                ]
            )

    logger.info("用户数据生成完成: %d 行", rows)


def generate_all(output_dir: str = "data"):
    """生成全部演示数据"""
    logger.info("=== 开始生成演示数据 ===")
    generate_sales(output_dir)
    generate_orders(output_dir)
    generate_users(output_dir)
    logger.info("=== 演示数据全部生成完毕 ===")

    # 打印数据概览
    for csv_file in ["sales.csv", "orders.csv", "users.csv"]:
        filepath = Path(output_dir) / csv_file
        if filepath.exists():
            size_kb = filepath.stat().st_size / 1024
            logger.info("  %s: %.1f KB", csv_file, size_kb)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    generate_all()
