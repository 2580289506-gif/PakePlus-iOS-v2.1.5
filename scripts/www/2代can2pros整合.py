import json
import os
from datetime import datetime, timedelta
import requests
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# ---- PyQt5 专业 GUI ----
try:
    from PyQt5 import QtCore, QtWidgets
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import (
        QApplication,
        QMainWindow,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QHBoxLayout,
        QWidget,
        QHeaderView,
        QMessageBox,
        QGroupBox,
    )

    # matplotlib 嵌入到 PyQt5，用于走势图
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - 在无 GUI 环境时忽略
    QtCore = None  # type: ignore
    QtWidgets = None  # type: ignore
    QTimer = None  # type: ignore
    QApplication = None  # type: ignore
    QMainWindow = None  # type: ignore
    QLabel = None  # type: ignore
    QPushButton = None  # type: ignore
    QTableWidget = None  # type: ignore
    QTableWidgetItem = None  # type: ignore
    QVBoxLayout = None  # type: ignore
    QHBoxLayout = None  # type: ignore
    QWidget = None  # type: ignore
    QHeaderView = None  # type: ignore
    QMessageBox = None  # type: ignore
    QGroupBox = None  # type: ignore
    FigureCanvas = None  # type: ignore
    Figure = None  # type: ignore

try:
    # BeautifulSoup is only needed if you want to parse the HTML history/trend tables.
    # The script will still work for JSON endpoints without it.
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None  # type: ignore


BASE_URL = "https://pc28yb.com/"
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "deepseek_token.txt")


@dataclass
class OpenRecord:
    section: str
    open_codes: List[int]
    open_time: str

    @property
    def total(self) -> int:
        return sum(self.open_codes[:3])

    @property
    def da_xiao(self) -> str:
        # 加拿大 28: 0–13 小，14–27 大
        return "大" if self.total >= 14 else "小"

    @property
    def dan_shuang(self) -> str:
        return "单" if self.total % 2 == 1 else "双"


class JND28Client:
    def __init__(self, base_url: str = BASE_URL, timeout: int = 10):
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            }
        )

    # ---- 原网站使用的接口封装 ----

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, as_json: bool = False) -> Any:
        url = self.base_url + path.lstrip("/")
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        if as_json:
            return resp.json()
        return resp.text

    def get_last_html(self) -> str:
        """
        对应前端: $.get("index.php?action=getLast")
        返回的是 HTML 片段 (最新一期显示块)。
        """
        return self._get("index.php", params={"action": "getLast"})

    def get_latest_history_html(self) -> str:
        """
        对应前端: $.get("index.php?action=getKaijiangLatest&ref=xxx")
        返回最近 20 条历史数据的表格 HTML。
        """
        return self._get(
            "index.php",
            params={"action": "getKaijiangLatest", "ref": "pc28yb.com"},
        )

    def get_trend_html(self) -> str:
        """
        对应前端: $.get("index.php?action=getTrend")
        返回走势表格 HTML。
        """
        return self._get("index.php", params={"action": "getTrend"})

    def get_statistic_json(self) -> List[Dict[str, Any]]:
        """
        对应前端: $.get("index.php?action=getStatisticJson")
        返回统计 JSON (前端直接传给 show_statistic)。
        """
        # 这个接口直接返回 JSON 字符串 (前端没有再 JSON.parse)
        text = self._get("index.php", params={"action": "getStatisticJson"})
        return json.loads(text)

    def get_guess_json(self) -> Dict[str, Any]:
        """
        对应前端: $.get("index.php?action=getMyOpensJson")
        返回最近若干期的详细开将数据 (section/openCode1...openCode10)。
        """
        text = self._get("index.php", params={"action": "getMyOpensJson"})
        return json.loads(text)

    def get_next_info(self) -> Dict[str, Any]:
        """
        对应前端: $.get("index.php?gameType=jnd28&action=next", ..., 'json')
        返回下一期开奖的倒计时与期号信息。
        """
        return self._get(
            "index.php",
            params={"gameType": "jnd28", "action": "next"},
            as_json=True,
        )

    def get_shazu_predictions(self) -> Dict[str, tuple]:
        """
        从网站杀组页面抓取2号预测数据
        返回 {期号: (预测显示, 对错)} 的字典
        """
        predictions = {}
        try:
            # 抓取杀组页面 http://www.xyyc28.top/jnd/jndsz.php
            html = self.session.get(
                "http://www.xyyc28.top/jnd/jndsz.php",
                timeout=self.timeout
            ).text
            
            if BeautifulSoup is None:
                return predictions
            
            soup = BeautifulSoup(html, "html.parser")
            tbody = soup.find("tbody", id="biaoge") or soup.find("tbody")
            if not tbody:
                return predictions
            
            for tr in tbody.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 5:
                    continue
                
                section = tds[0].get_text(strip=True)
                
                # 解析预测列
                pred_td = tds[3]
                fonts = pred_td.find_all("font")
                if len(fonts) >= 2:
                    part1 = fonts[0].get_text(strip=True)
                    part2 = fonts[1].get_text(strip=True)
                    pred_display = f"{part1} + {part2}"
                else:
                    pred_display = pred_td.get_text(strip=True)
                
                # 解析对错列
                result_td = tds[4]
                result_text = result_td.get_text(strip=True)
                if "正确" in result_text:
                    result = "对"
                elif "错误" in result_text:
                    result = "错"
                else:
                    result = ""
                
                predictions[section] = (pred_display, result)
        except Exception:
            pass
        
        return predictions

    # ---- 数据整理与简单分析 ----

    def get_latest_open_records(self, limit: int = 20) -> List[OpenRecord]:
        """
        使用 getMyOpensJson 接口，整理成 Python 对象列表。
        """
        raw = self.get_guess_json()
        data = raw.get("data", [])
        records: List[OpenRecord] = []
        for item in data[:limit]:
            codes = []
            for i in range(1, 11):
                key = f"openCode{i}"
                try:
                    codes.append(int(item.get(key, "0")))
                except (TypeError, ValueError):
                    codes.append(0)
            records.append(
                OpenRecord(
                    section=str(item.get("section", "")),
                    open_codes=codes,
                    open_time=str(item.get("openTime", "")),
                )
            )
        return records

    def simple_statistics(self, records: List[OpenRecord]) -> Dict[str, Any]:
        """
        对最近 N 期做一个简易统计：大小、单双的次数分布。
        """
        stats = {
            "total_count": len(records),
            "大": 0,
            "小": 0,
            "单": 0,
            "双": 0,
        }
        for r in records:
            stats[r.da_xiao] += 1
            stats[r.dan_shuang] += 1
        return stats

    def parse_history_table(self, html: str) -> List[Dict[str, Any]]:
        """
        如果安装了 beautifulsoup4，可解析 `getKaijiangLatest` 返回的 HTML 表格。
        解析字段会根据页面结构适当调整。
        """
        if BeautifulSoup is None:
            raise RuntimeError("需要安装 beautifulsoup4 才能解析 HTML 表格")

        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("tbody") or soup
        rows = []
        for tr in tbody.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not tds:
                continue
            rows.append({"cols": tds})
        return rows

# ----------------- 命令行模式（保留） -----------------

def cli_main():
    """命令行模式主函数（保留原来的输出）。"""
    client = JND28Client()

    # 1. 获取下一期开奖信息
    try:
        next_info = client.get_next_info()
        print("下一期信息:")
        print(f"  期号: {next_info.get('section')}")
        print(f"  倒计时(秒): {next_info.get('djs')}")
    except Exception as e:
        print("获取下一期信息失败:", e)

    print("\n最近 20 期 开奖结果 (基于 getMyOpensJson):")
    try:
        records = client.get_latest_open_records(limit=20)
        for r in records:
            print(
                f"期号 {r.section}  时间 {r.open_time}  "
                f"号码 {r.open_codes[:3]}  和值 {r.total}  {r.da_xiao}{r.dan_shuang}"
            )

        stats = client.simple_statistics(records)
        print("\n最近 20 期 简易统计:")
        print(f"  总期数: {stats['total_count']}")
        print(f"  大: {stats['大']}, 小: {stats['小']}")
        print(f"  单: {stats['单']}, 双: {stats['双']}")
    except Exception as e:
        print("获取或分析历史数据失败:", e)

    # 3. 获取统计面板原始 JSON (与网页上的“遗漏统计”一致)
    try:
        stat_json = client.get_statistic_json()
        print("\n原始统计 JSON 示例(首条记录的部分键):")
        if stat_json:
            first = stat_json[0]
            demo_keys = ["大", "小", "单", "双", "极大", "极小"]
            for k in demo_keys:
                if k in first:
                    print(f"  {k}: {first[k]}")
    except Exception as e:
        print("获取统计 JSON 失败:", e)


# ----------------- PyQt5 专业 GUI -----------------

class TrendCanvas(FigureCanvas):
    """封装一个 matplotlib 画布，用于显示和值走势图。"""

    def __init__(self, parent: Optional[QWidget] = None):
        fig = Figure(figsize=(4, 3), dpi=100)
        self.ax = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.ax.set_title("和值走势")
        self.ax.set_xlabel("期数（从旧到新）")
        self.ax.set_ylabel("和值")
        self.ax.grid(True, linestyle="--", alpha=0.3)

    def update_trend(self, records: List[OpenRecord]):
        self.ax.clear()
        self.ax.set_title("和值走势")
        self.ax.set_xlabel("期数（从旧到新）")
        self.ax.set_ylabel("和值")
        self.ax.grid(True, linestyle="--", alpha=0.3)

        if not records:
            self.draw()
            return

        # 按时间顺序（旧 -> 新）绘制
        ordered = list(reversed(records))
        totals = [r.total for r in ordered]
        xs = list(range(1, len(ordered) + 1))
        self.ax.plot(xs, totals, marker="o", color="#0078d4")
        self.ax.set_ylim(-1, 28)
        self.draw()


class JND28Window(QMainWindow):
    """PyQt5 主窗口：显示当前期、倒计时、历史表格、走势图和统计分析。"""

    PERIOD_SECONDS = 210  # 每期 3 分 30 秒（用户说明）

    def __init__(self, parent: Optional[QWidget] = None):
        if QMainWindow is None:
            raise RuntimeError("当前环境不支持 PyQt5，无法启动 GUI")

        super().__init__(parent)
        self.setWindowTitle("加拿大28 分析工具 2代 - PC28  |  Q群：981935811  飞机：@laomao12315")
        # 窗口尺寸扩大
        self.resize(1400, 900)

        self.client = JND28Client()
        # DeepSeek AI 相关配置
        self.deepseek_token: str = ""
        self.latest_records: List[OpenRecord] = []
        self.ai_predictions_by_issue: Dict[str, str] = {}
        self.current_section: str = ""
        self.next_section: str = ""
        # 当前预测的简要描述（用于“本期期号”后面显示）
        self.current_guess_desc: str = ""
        # 本地倒计时（用于“本期剩余时间”显示）
        self.remaining_seconds: int = 0
        # 与服务器倒计时同步的值（用于“服务器倒计时”标签，每秒一起减）
        self.server_djs_seconds: int = 0

        # ---- 倒计时面板（大号数字 + 上一期/本期信息） ----
        panel_group = QGroupBox()
        panel_layout = QVBoxLayout()
        panel_group.setLayout(panel_layout)

        self.label_big_timer = QLabel("00:00")
        self.label_big_timer.setAlignment(QtCore.Qt.AlignCenter)
        self.label_big_timer.setStyleSheet(
            "font-size: 40px; color: #d00000; font-weight: bold; "
            "padding: 8px; border: 2px solid #d00000; border-radius: 6px;"
        )

        self.label_prev_summary = QLabel("上一期：--")
        self.label_prev_summary.setStyleSheet(
            "font-size: 13px; padding-top: 4px; font-weight: bold;"
        )
        self.label_current_issue = QLabel("本期期号：--")
        self.label_current_issue.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.label_open_time = QLabel("预计开奖时间：--")
        self.label_open_time.setStyleSheet(
            "font-size: 12px; color: #666666; font-weight: bold;"
        )

        # 固定的三个预测框
        prediction_layout = QHBoxLayout()
        prediction_layout.setSpacing(10)
        
        # 老猫预测框
        self.label_laomao_pred = QLabel("老猫预测：--")
        self.label_laomao_pred.setStyleSheet(
            "font-size: 13px; color: #b21824; font-weight: bold; "
            "padding: 6px 12px; border: 2px solid #b21824; border-radius: 4px; "
            "background-color: #fff5f5; min-width: 200px;"
        )
        self.label_laomao_pred.setAlignment(QtCore.Qt.AlignCenter)
        
        # 2号预测框
        self.label_kill2_pred = QLabel("2号预测：--")
        self.label_kill2_pred.setStyleSheet(
            "font-size: 13px; color: #d35400; font-weight: bold; "
            "padding: 6px 12px; border: 2px solid #d35400; border-radius: 4px; "
            "background-color: #fff8f0; min-width: 200px;"
        )
        self.label_kill2_pred.setAlignment(QtCore.Qt.AlignCenter)
        
        # AI预测框
        self.label_ai_pred_top = QLabel("AI预测：--")
        self.label_ai_pred_top.setStyleSheet(
            "font-size: 13px; color: #335397; font-weight: bold; "
            "padding: 6px 12px; border: 2px solid #335397; border-radius: 4px; "
            "background-color: #f0f5ff; min-width: 200px;"
        )
        self.label_ai_pred_top.setAlignment(QtCore.Qt.AlignCenter)
        
        prediction_layout.addWidget(self.label_laomao_pred)
        prediction_layout.addWidget(self.label_kill2_pred)
        prediction_layout.addWidget(self.label_ai_pred_top)
        prediction_layout.addStretch()

        panel_layout.addWidget(self.label_big_timer)
        panel_layout.addWidget(self.label_prev_summary)
        panel_layout.addWidget(self.label_current_issue)
        panel_layout.addLayout(prediction_layout)
        panel_layout.addWidget(self.label_open_time)

        # ---- 顶部信息区 ----
        top_group = QGroupBox("期数与倒计时")
        top_layout = QHBoxLayout()
        top_group.setLayout(top_layout)

        self.label_current_section = QLabel("当前期数：--")
        self.label_next_section = QLabel("下一期：--")
        self.label_remaining = QLabel("本期剩余时间：--:--")
        self.label_server_djs = QLabel("服务器倒计时：-- 秒")

        for lbl in [
            self.label_current_section,
            self.label_next_section,
            self.label_remaining,
            self.label_server_djs,
        ]:
            lbl.setStyleSheet(
                "font-size: 14px; padding: 2px 8px; font-weight: bold;"
            )

        self.btn_refresh = QPushButton("立即刷新")
        self.btn_refresh.setStyleSheet(
            "QPushButton {background-color: #0078d4; color: white; padding: 6px 16px; "
            "border-radius: 4px;}"
            "QPushButton:hover {background-color: #005a9e;}"
        )
        self.btn_refresh.clicked.connect(self.manual_refresh)

        top_layout.addWidget(self.label_current_section)
        top_layout.addWidget(self.label_next_section)
        top_layout.addWidget(self.label_remaining)
        top_layout.addWidget(self.label_server_djs)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)

        # ---- 中间：左侧表格 + 右侧走势图 ----
        center_layout = QHBoxLayout()

        # 历史记录表格
        table_group = QGroupBox("历史记录（最新 50 期）")
        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels(
            ["期号", "时间", "号码1", "号码2", "号码3", "和值", "大小单双", "老猫预测对错", "2号杀组对错", "AI预测对错", "老猫20期胜率", "2号20期胜率", "AI20期胜率"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget {font-size: 12px; font-weight: bold;} "
            "QHeaderView::section {background:#e5e5e5; font-weight: bold;}"
        )

        table_vbox = QVBoxLayout()
        table_vbox.addWidget(self.table)
        table_group.setLayout(table_vbox)

        # 走势图
        trend_group = QGroupBox("走势图")
        trend_vbox = QVBoxLayout()
        self.trend_canvas = TrendCanvas()
        trend_vbox.addWidget(self.trend_canvas)
        trend_group.setLayout(trend_vbox)

        center_layout.addWidget(table_group, stretch=3)
        center_layout.addWidget(trend_group, stretch=2)

        # ---- 底部：统计分析 ----
        bottom_group = QGroupBox("数据分析")
        bottom_layout = QVBoxLayout()
        bottom_group.setLayout(bottom_layout)

        self.label_stats_main = QLabel("最近 0 期统计：大 0  小 0  单 0  双 0")
        self.label_stats_main.setStyleSheet("font-size: 13px; font-weight: bold;")

        self.label_streak = QLabel("连开情况：--")
        self.label_streak.setStyleSheet("font-size: 13px; font-weight: bold;")

        self.label_predict = QLabel("预测：--")
        self.label_predict.setStyleSheet(
            "font-size: 13px; color: #b21824; font-weight: bold;"
        )

        bottom_layout.addWidget(self.label_stats_main)
        bottom_layout.addWidget(self.label_streak)
        bottom_layout.addWidget(self.label_predict)

        # DeepSeek 配置与 AI 预测结果
        ai_cfg_layout = QHBoxLayout()
        self.edit_token = QtWidgets.QLineEdit()
        self.edit_token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_token.setPlaceholderText("在此输入 DeepSeek API Token")
        self.edit_token.setMinimumWidth(260)
        label_token = QLabel("DeepSeek Token：")
        label_token.setStyleSheet("font-size: 12px; font-weight: bold;")

        self.btn_ai_predict = QPushButton("AI 预测当前期")
        self.btn_ai_predict.setStyleSheet(
            "QPushButton {background-color: #16a085; color: white; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;}"
            "QPushButton:hover {background-color: #13856e;}"
        )
        self.btn_ai_predict.clicked.connect(self.on_ai_predict_clicked)

        ai_cfg_layout.addWidget(label_token)
        ai_cfg_layout.addWidget(self.edit_token)
        ai_cfg_layout.addWidget(self.btn_ai_predict)
        ai_cfg_layout.addStretch()
        bottom_layout.addLayout(ai_cfg_layout)

        self.label_ai_predict = QLabel("AI 预测：--")
        self.label_ai_predict.setStyleSheet(
            "font-size: 13px; color: #335397; font-weight: bold;"
        )
        bottom_layout.addWidget(self.label_ai_predict)

        # 联系方式按钮
        contact_btn = QPushButton("联系方式 / 免责声明")
        contact_btn.setStyleSheet(
            "QPushButton {background-color: #e67e22; color: white; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;}"
            "QPushButton:hover {background-color: #d35400;}"
        )
        contact_btn.clicked.connect(self.show_contact_dialog)
        bottom_layout.addWidget(contact_btn, alignment=QtCore.Qt.AlignLeft)

        # ---- 整体布局 ----
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addWidget(panel_group)
        main_layout.addWidget(top_group)
        main_layout.addLayout(center_layout)
        main_layout.addWidget(bottom_group)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # ---- 定时器：每秒更新倒计时，到期自动拉数据 ----
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.on_timer_tick)
        self.timer.start()

        # 读取本地保存的 DeepSeek Token（如有）
        self._load_deepseek_token()

        # 首次加载数据
        QtCore.QTimer.singleShot(100, self.auto_refresh_from_server)

    # ----------------- 数据加载与刷新逻辑 -----------------

    def _load_deepseek_token(self):
        """从本地文件读取 DeepSeek Token，如果存在则自动填充。"""
        try:
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    token = f.read().strip()
                    if token:
                        self.deepseek_token = token
                        self.edit_token.setText(token)
        except Exception:
            # 读取失败不影响主流程
            pass

    def _save_deepseek_token(self, token: str):
        """将 DeepSeek Token 保存到本地文件。"""
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(token)
        except Exception:
            # 写入失败也不影响主流程
            pass

    def auto_refresh_from_server(self):
        """从服务器拉取最新期数和数据，并重置本地倒计时。"""
        try:
            next_info = self.client.get_next_info()
            next_section = str(next_info.get("section", ""))
            djs = int(next_info.get("djs", self.PERIOD_SECONDS))

            # 当前期数 = 下一期 - 1（大多数 PC28 站是这样）
            try:
                cur = str(int(next_section) - 1)
            except ValueError:
                cur = "--"

            self.current_section = cur
            self.next_section = next_section
            self.remaining_seconds = djs
            self.server_djs_seconds = djs

            self.label_current_section.setText(f"当前期数：{cur}")
            self.label_next_section.setText(f"下一期：{next_section}")
            self.label_current_issue.setText(f"本期期号：{next_section}")

            # 预计开奖时间 = 当前时间 + 剩余秒数
            eta = datetime.now() + timedelta(seconds=djs)
            self.label_open_time.setText(
                f"预计开奖时间：{eta.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            self.label_server_djs.setText(f"服务器倒计时：{djs} 秒")
            self.update_remaining_label()

            self.load_history_and_statistics()

            # 如果已经配置了 DeepSeek Token，随着新一期数据自动进行 AI 预测
            if self.deepseek_token:
                self._run_ai_predict(auto=True)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取下一期信息失败：\n{e}")

    def manual_refresh(self):
        """手动点击按钮刷新。"""
        self.auto_refresh_from_server()

    def load_history_and_statistics(self):
        """加载历史记录（更多期数）、预测对错，并更新表格、走势图和统计。"""
        try:
            # 用 getMyOpensJson：最多可能返回 100 期，这里截 50 期显示
            raw = self.client.get_guess_json()
            data = raw.get("data", [])
            records: List[OpenRecord] = []
            for item in data[:50]:
                codes = []
                for i in range(1, 11):
                    key = f"openCode{i}"
                    try:
                        codes.append(int(item.get(key, "0")))
                    except (TypeError, ValueError):
                        codes.append(0)
                records.append(
                    OpenRecord(
                        section=str(item.get("section", "")),
                        open_codes=codes,
                        open_time=str(item.get("openTime", "")),
                    )
                )

            # 保存到实例，供 AI 预测使用
            self.latest_records = records

            # 先按时间从早到晚排序，用于计算“上一期预测这一期”的对错
            ordered_old_to_new = sorted(records, key=lambda r: r.open_time)
            predict_result_by_section: Dict[str, str] = {}
            for i in range(len(ordered_old_to_new) - 1):
                base = ordered_old_to_new[i]      # 用 base 期的号码预测下一期
                target = ordered_old_to_new[i + 1]  # 实际开奖号码所在期

                if len(base.open_codes) < 3 or len(target.open_codes) < 3:
                    continue

                n1, n2, n3 = base.open_codes[0], base.open_codes[1], base.open_codes[2]
                guess_dx = "大" if (n2 + n3) > 13 else "小"
                guess_ds = "单" if (n1 + n2) % 2 == 1 else "双"

                # 按你说的规则：大小单双其中一个对就算对
                correct = (guess_dx == target.da_xiao) or (guess_ds == target.dan_shuang)
                predict_result_by_section[target.section] = "对" if correct else "错"

            # 再按时间倒序：离当前时间最近的在最上面
            sorted_by_time = sorted(records, key=lambda r: r.open_time, reverse=True)

            # 更新倒计时面板里的“上一期”信息：使用表格第一行（也就是最新一期）
            if sorted_by_time:
                last = sorted_by_time[0]
                combo = f"{last.da_xiao}{last.dan_shuang}"
                spans = []
                for n in last.open_codes[:3]:
                    spans.append(
                        f"<span style='display:inline-block;min-width:22px;"
                        f"padding:2px 6px;margin:0 2px;background:#0078d4;"
                        f"color:#ffffff;border-radius:3px;text-align:center;'>{n}</span>"
                    )
                nums_html = "".join(spans)
                html = (
                    f"上一期：{last.section}  {nums_html}  "
                    f"<span style='color:#d00000;font-weight:bold;'>{combo}</span>"
                )
                self.label_prev_summary.setText(html)

                # 同时基于最新一期做下一期预测
                self.update_prediction(last)

            # 尝试从网站抓取2号杀组预测
            shazu_predictions = self.client.get_shazu_predictions()
            
            # 更新表格（带老猫预测对错 & 2号杀组 & AI 预测对错）
            self.populate_table(sorted_by_time, predict_result_by_section, shazu_predictions)

            # 更新走势图（和值）
            self.trend_canvas.update_trend(records[:30])  # 只画最近 30 期，避免太挤

            # 更新统计与连开分析
            self.update_statistics(records)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取历史数据失败：\n{e}")

    def calculate_win_rate(self, records: List[OpenRecord], predict_result_by_section: Dict[str, str], 
                           shazu_predictions: Dict[str, tuple], ai_predictions: Dict[str, str], 
                           model_type: str, start_index: int, period_count: int = 20) -> str:
        """
        计算指定模型的胜率
        model_type: "laomao", "kill2", "ai"
        start_index: 从records的哪个索引开始计算（从0开始，0是最新一期）
        period_count: 计算多少期的胜率，默认20期
        注意：records是从新到旧排列的，所以从start_index往后取period_count期
        """
        if start_index >= len(records):
            return "--"
        
        # 获取要计算的期数范围（从start_index往后取period_count期，因为records是从新到旧）
        end_index = min(len(records), start_index + period_count)
        target_records = records[start_index:end_index]
        
        if not target_records:
            return "--"
        
        correct_count = 0
        total_count = 0
        
        for r in target_records:
            if model_type == "laomao":
                hit = predict_result_by_section.get(r.section, "")
                if hit:
                    total_count += 1
                    if hit == "对":
                        correct_count += 1
            elif model_type == "kill2":
                if r.section in shazu_predictions:
                    _, kill_2_hit = shazu_predictions[r.section]
                    if kill_2_hit:
                        total_count += 1
                        if kill_2_hit == "对":
                            correct_count += 1
            elif model_type == "ai":
                ai_combo = ai_predictions.get(r.section)
                if ai_combo:
                    ai_dx = ai_combo[0] if ai_combo and ai_combo[0] in ("大", "小") else ""
                    ai_ds = ai_combo[1] if len(ai_combo) > 1 and ai_combo[1] in ("单", "双") else ""
                    if ai_dx or ai_ds:
                        total_count += 1
                        correct = (ai_dx == r.da_xiao) or (ai_ds == r.dan_shuang)
                        if correct:
                            correct_count += 1
        
        if total_count == 0:
            return "--"
        
        win_rate = (correct_count / total_count) * 100
        return f"{win_rate:.1f}%"

    def populate_table(self, records: List[OpenRecord], predict_result_by_section: Dict[str, str], shazu_predictions: Dict[str, tuple] = None):
        if shazu_predictions is None:
            shazu_predictions = {}
        
        self.table.setRowCount(len(records))
        for row, r in enumerate(records):
            combo = f"{r.da_xiao}{r.dan_shuang}"
            hit = predict_result_by_section.get(r.section, "")  # 老猫预测对错
            
            # 2号预测对错：优先使用网站抓取的数据
            kill_2_hit = ""
            if r.section in shazu_predictions:
                _, kill_2_hit = shazu_predictions[r.section]
            
            ai_hit = ""
            ai_combo = self.ai_predictions_by_issue.get(r.section)
            if ai_combo:
                # 解析 AI 预测的大/小、单/双
                ai_dx = ai_combo[0] if ai_combo and ai_combo[0] in ("大", "小") else ""
                ai_ds = ai_combo[1] if len(ai_combo) > 1 and ai_combo[1] in ("单", "双") else ""
                if ai_dx or ai_ds:
                    correct = (ai_dx == r.da_xiao) or (ai_ds == r.dan_shuang)
                    ai_hit = "对" if correct else "错"

            # 计算20期胜率（从当前行往前20期）
            laomao_rate = self.calculate_win_rate(records, predict_result_by_section, shazu_predictions, 
                                                  self.ai_predictions_by_issue, "laomao", row, 20)
            kill2_rate = self.calculate_win_rate(records, predict_result_by_section, shazu_predictions, 
                                                 self.ai_predictions_by_issue, "kill2", row, 20)
            ai_rate = self.calculate_win_rate(records, predict_result_by_section, shazu_predictions, 
                                             self.ai_predictions_by_issue, "ai", row, 20)

            values = [
                r.section,
                r.open_time,
                str(r.open_codes[0]),
                str(r.open_codes[1]),
                str(r.open_codes[2]),
                str(r.total),
                combo,
                hit,
                kill_2_hit,
                ai_hit,
                laomao_rate,
                kill2_rate,
                ai_rate,
            ]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                # 老猫预测对错列 / 2号杀组对错列 / AI 预测对错列：对 -> 绿色，错 -> 红色
                if col in (7, 8, 9) and v:
                    if v == "对":
                        item.setForeground(QtCore.Qt.green)
                    else:
                        item.setForeground(QtCore.Qt.red)
                # 胜率列：设置样式
                elif col in (10, 11, 12):
                    if v != "--":
                        # 胜率>=50%显示绿色，<50%显示红色
                        try:
                            rate_value = float(v.replace("%", ""))
                            if rate_value >= 50:
                                item.setForeground(QtCore.Qt.green)
                            else:
                                item.setForeground(QtCore.Qt.red)
                        except:
                            pass
                self.table.setItem(row, col, item)

    def update_statistics(self, records: List[OpenRecord]):
        if not records:
            self.label_stats_main.setText("最近 0 期统计：大 0  小 0  单 0  双 0")
            self.label_streak.setText("连开情况：--")
            return

        stats = self.client.simple_statistics(records)
        self.label_stats_main.setText(
            f"最近 {stats['total_count']} 期统计："
            f"大 {stats['大']}  小 {stats['小']}  单 {stats['单']}  双 {stats['双']}"
        )

        # 简单连开分析：最近连续的大/小/单/双
        last = records[0]  # 最新一期
        last_dx = last.da_xiao
        last_ds = last.dan_shuang

        streak_dx = 0
        streak_ds = 0
        for r in records:
            if r.da_xiao == last_dx:
                streak_dx += 1
            else:
                break

        for r in records:
            if r.dan_shuang == last_ds:
                streak_ds += 1
            else:
                break

        self.label_streak.setText(
            f"连开情况：最近 {streak_dx} 期都是「{last_dx}」，"
            f"最近 {streak_ds} 期都是「{last_ds}」"
        )

    # ----------------- 预测逻辑（参考网页 JS） -----------------

    def format_prediction_display(self, prediction: str) -> str:
        """
        将预测结果转换为新的显示格式
        例如：
        - "大单" -> "大单大双小单"
        - "大双" -> "大单大双小双"
        - "小单" -> "大单小单小双"
        - "小双" -> "大双小单小双"
        - "大+小双" -> "大单大双小双"
        - "小+大单" -> "大单小单小双"
        """
        if not prediction or prediction == "未知" or prediction == "获取中...":
            return prediction
        
        # 处理2号预测格式 "大+小双" 或 "小+大单" 等
        if "+" in prediction:
            parts = prediction.split("+")
            if len(parts) == 2:
                part1 = parts[0].strip()
                part2 = parts[1].strip()
                
                # 解析part2（大单/大双/小单/小双）
                if len(part2) == 2 and part2[0] in ("大", "小") and part2[1] in ("单", "双"):
                    dx2, ds2 = part2[0], part2[1]
                else:
                    return prediction
                
                # 根据part1和part2组合结果
                # part1表示推荐的方向（大/小/单/双），part2表示推荐的组合
                # 结果包含：part1方向的所有组合 + part2组合（去重）
                result_list = []
                
                # 根据part1添加对应的组合（按特定顺序）
                if part1 == "大":
                    result_list = ["大单", "大双"]
                elif part1 == "小":
                    result_list = ["小双", "小单"]  # 注意顺序：小双在前
                elif part1 == "单":
                    result_list = ["大单", "小单"]
                elif part1 == "双":
                    result_list = ["大双", "小双"]  # 注意顺序：大双在前
                
                # 添加part2组合（如果不在列表中）
                if part2 not in result_list:
                    result_list.append(part2)
                
                return "".join(result_list)
        
        # 处理标准格式 "大单"、"大双"、"小单"、"小双"
        # 规则：预测X，显示为X + 同大小的另一个 + 同单双的另一个
        if prediction == "大单":
            # 大单 -> 大单、大双、小单
            return "大单大双小单"
        elif prediction == "大双":
            # 大双 -> 大单、大双、小双
            return "大单大双小双"
        elif prediction == "小单":
            # 小单 -> 大单、小单、小双
            return "大单小单小双"
        elif prediction == "小双":
            # 小双 -> 大双、小单、小双
            return "大双小单小双"
        
        return prediction

    def predict_kill_group_2(self, section: str, prev_record: Optional[OpenRecord] = None) -> tuple:
        """
        2号预测：杀组算法
        根据上一期的三个开奖号码决定预测和杀组
        
        显示格式"A + B"的含义：
        - A是大/小或单/双
        - B是组合（如大双）
        - 例如"小+大双"：推荐小或大双，开出小或大双都算对
        
        规则（基于网站数据分析）：
        第一位(A)的规则：
        - n1+n2奇数且<=9 → 双
        - n1+n2奇数且>9 → 单
        - n1+n2偶数且<=8 → 小
        - n1+n2偶数且>8 → 单
        
        组合(B)的规则：
        - 大小：n2+n3<=13→大，>13→小
        - 单双：与第一位相反（第一位是单→双，双→单，大→单，小→双）
        
        返回 (预测显示字符串, 杀组)
        """
        if prev_record is None or len(prev_record.open_codes) < 3:
            return ("未知", "未知")
        
        n1, n2, n3 = prev_record.open_codes[0], prev_record.open_codes[1], prev_record.open_codes[2]
        
        sum_n1n2 = n1 + n2
        sum_n2n3 = n2 + n3
        
        # 第一位(A)
        if sum_n1n2 % 2 == 1:  # 奇数
            rec_first = "双" if sum_n1n2 <= 9 else "单"
        else:  # 偶数
            if sum_n1n2 <= 4:
                rec_first = "双"
            elif sum_n1n2 <= 8:
                rec_first = "小"
            else:
                rec_first = "单"
        
        # 组合大小
        combo_dx = "大" if sum_n2n3 <= 13 else "小"
        
        # 组合单双：与第一位相反
        if rec_first == "单":
            combo_ds = "双"
        elif rec_first == "双":
            combo_ds = "单"
        elif rec_first == "大":
            combo_ds = "单"
        else:  # 小
            combo_ds = "双"
        
        rec_combo = combo_dx + combo_ds
        display = f"{rec_first} + {rec_combo}"
        
        # 杀组 = 第一位的反面 + 组合单双的反面
        if rec_first in ("大", "小"):
            kill_dx = "大" if rec_first == "小" else "小"
            kill_ds = "单" if combo_ds == "双" else "双"
        else:  # 单/双
            kill_ds = "单" if rec_first == "双" else "双"
            kill_dx = "小" if combo_dx == "大" else "大"
        kill_group = kill_dx + kill_ds
        
        return (display, kill_group)

    def update_prediction(self, last: OpenRecord):
        """
        参考源码中的 JS 规则：
        - 预测大小：n2 + n3 > 13 则"大"，否则"小"
        - 预测单双：n1 + n2 为奇数则"单"，否则"双"
        """
        if len(last.open_codes) < 3:
            self.label_predict.setText("预测：数据不足")
            self.label_laomao_pred.setText("老猫预测：数据不足")
            self.label_kill2_pred.setText("2号预测：数据不足")
            return

        n1, n2, n3 = last.open_codes[0], last.open_codes[1], last.open_codes[2]

        guess_dx = "大" if (n2 + n3) > 13 else "小"
        guess_ds = "单" if (n1 + n2) % 2 == 1 else "双"

        # 组合预测与"杀组"参考网页逻辑
        combo = guess_dx + guess_ds
        kill_combo = ("小" if guess_dx == "大" else "大") + ("双" if guess_ds == "单" else "单")

        # 预测的下一期期号 = 最新一期 + 1（防止异常转 int 失败）
        try:
            next_section = str(int(last.section) + 1)
        except ValueError:
            next_section = "未知"

        # 2号预测：尝试从网站获取
        kill_display_2 = "获取中..."
        try:
            shazu_predictions = self.client.get_shazu_predictions()
            if next_section in shazu_predictions:
                kill_display_2, _ = shazu_predictions[next_section]
        except Exception:
            pass

        # 缓存简要预测描述，供"本期期号"后面使用
        self.current_guess_desc = f"{combo}（大小 {guess_dx} / 单双 {guess_ds}）"

        # 老猫预测（规则策略）+ 2号预测
        self.label_predict.setText(
            f"预测下一期（{next_section}）：组合 {combo}，杀组 {kill_combo}，"
            f"大小 {guess_dx}，单双 {guess_ds}    |    2号预测：{kill_display_2}"
        )

        # 更新固定的预测框
        laomao_display = self.format_prediction_display(combo)
        self.label_laomao_pred.setText(f"老猫预测：{laomao_display}")
        
        kill2_display = self.format_prediction_display(kill_display_2)
        self.label_kill2_pred.setText(f"2号预测：{kill2_display}")

        # 同步更新顶部"本期期号"行（只显示期号，不显示预测）
        if self.next_section:
            self.label_current_issue.setText(f"本期期号：{self.next_section}")

    # ----------------- DeepSeek AI 预测 -----------------

    def on_ai_predict_clicked(self):
        """点击按钮，使用 DeepSeek + 历史数据进行 AI 预测当前期大小单双，并保存 Token。"""
        token = self.edit_token.text().strip()
        if not token:
            QMessageBox.warning(self, "提示", "请先在下方输入 DeepSeek API Token。")
            return

        self.deepseek_token = token
        self._save_deepseek_token(token)
        self._run_ai_predict(auto=False)

    def _run_ai_predict(self, auto: bool = False):
        """执行一次 AI 预测，auto=True 时静默失败。"""
        token = self.deepseek_token or self.edit_token.text().strip()
        if not token:
            if not auto:
                QMessageBox.warning(self, "提示", "请先配置 DeepSeek API Token。")
            return

        if not self.latest_records or not self.next_section:
            if not auto:
                QMessageBox.warning(self, "提示", "暂无历史数据，无法进行 AI 预测。")
            return

        # 取最近 N 期作为上下文（从新到旧，越靠前越新）
        N = 20
        ordered = sorted(self.latest_records, key=lambda r: r.open_time, reverse=True)
        context_records = ordered[:N]

        history_lines = []
        for r in context_records:
            history_lines.append(
                f"期号 {r.section} 和值 {r.total} 大小 {r.da_xiao} 单双 {r.dan_shuang}"
            )
        history_text = "\n".join(history_lines)

        target_issue = self.next_section

        prompt = (
            "你是一个只做数据统计和模式分析的助手，专门分析加拿大28（PC28）历史开奖结果的走势，"
            "根据最近的历史数据，预测**下一期**的大小单双。\n\n"
            "注意：下面的历史数据**第一行是最新一期**，往下越旧，只看这些数据来做判断。\n"
            "历史数据格式：期号 和值 大小 单双。\n"
            "以下是最近的历史数据（从新到旧）：\n"
            f"{history_text}\n\n"
            f"现在要预测的期号是：{target_issue}。\n"
            "请只基于上面这些最近数据给出一个客观的推测结果，"
            "并且严格只输出以下 4 个结果之一：大单、大双、小单、小双。"
            "不要输出其他任何文字。"
        )

        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一个加拿大28走势分析助手。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.6,
                "max_tokens": 16,
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            ai_text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            # 只保留第一个有效关键词
            for kw in ["大单", "大双", "小单", "小双"]:
                if kw in ai_text:
                    ai_text = kw
                    break

            if ai_text in ["大单", "大双", "小单", "小双"]:
                # 记录 AI 预测，用于之后的历史对错统计
                self.ai_predictions_by_issue[target_issue] = ai_text

            self.label_ai_predict.setText(
                f"AI 预测（{target_issue}）：{ai_text or '获取失败'}"
            )

            # 更新固定的AI预测框
            if ai_text in ["大单", "大双", "小单", "小双"]:
                ai_display = self.format_prediction_display(ai_text)
                self.label_ai_pred_top.setText(f"AI预测：{ai_display}")
            else:
                self.label_ai_pred_top.setText(f"AI预测：{ai_text or '获取失败'}")

        except Exception as e:
            if not auto:
                QMessageBox.warning(self, "AI 预测失败", f"调用 DeepSeek 接口出错：\n{e}")
            # 更新AI预测框显示失败信息
            self.label_ai_pred_top.setText("AI预测：获取失败")

    def show_contact_dialog(self):
        """显示联系方式和免责声明。"""
        text = (
            "【联系方式】\n"
            "Q群：981935811\n"
            "Telegram（飞机）：@laomao12315\n\n"
            "【免责声明】\n"
            "本工具仅用于数据展示和走势分析，不提供任何形式的投注建议或保证盈利。\n"
            "彩票、游戏等具有高风险，请理性参与，自负盈亏。"
        )
        QMessageBox.information(self, "联系方式 / 免责声明", text)

    # ----------------- 定时器逻辑 -----------------

    def update_remaining_label(self):
        m = max(self.remaining_seconds, 0) // 60
        s = max(self.remaining_seconds, 0) % 60
        text = f"{m:02d}:{s:02d}"
        # 小号文字提示
        self.label_remaining.setText(f"本期剩余时间：{text}")
        # 大号红色数字
        self.label_big_timer.setText(text)

    def on_timer_tick(self):
        # 本地倒计时（本期剩余时间）
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
        self.update_remaining_label()

        # 服务器倒计时标签也每秒刷新一次（与刚同步的 djs 一起递减）
        if self.server_djs_seconds > 0:
            self.server_djs_seconds -= 1
        self.label_server_djs.setText(f"服务器倒计时：{max(self.server_djs_seconds, 0)} 秒")

        # 当本地剩余时间归零时，自动从服务器重新获取，重新同步倒计时
        if self.remaining_seconds <= 0:
            self.auto_refresh_from_server()


if __name__ == "__main__":
    # 默认启动 PyQt5 GUI，如需命令行模式可改为 cli_main()
    if QApplication is None:
        # 回退到命令行模式
        cli_main()
    else:
        import sys

        app = QApplication(sys.argv)
        window = JND28Window()
        window.show()
        sys.exit(app.exec_())


