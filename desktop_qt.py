#!/usr/bin/env python3
"""Native desktop shell for the chart assistant (PySide6 + QtWebEngine).

The local HTTP server stays the single data plane. This process adds a real
desktop window, native menu/toolbar/tray, single-instance focus, server health
watchdog, provider settings and chart/CSV export.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener

# Must be set before QtWebEngine initialises. The window only loads loopback
# content; the bundled Chromium sandbox is unreliable on some Linux desktops.
os.environ.setdefault('QTWEBENGINE_DISABLE_SANDBOX', '1')

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / 'logs' / 'desktop-qt.log'
CONFIG_PATH = ROOT / '.local.json'
VERSION = '0.6.3'


def log(message):
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{stamp}] {message}'
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    except OSError:
        pass
    try:
        if sys.stderr and not sys.stderr.closed:
            print(line, file=sys.stderr, flush=True)
    except Exception:
        pass


def venv_python():
    return ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def ensure_venv(offline):
    local = venv_python()
    if offline or not local.is_file():
        return
    try:
        if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
            os.execv(str(local), [str(local), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError as exc:
        log(f'venv re-exec failed: {exc}')


def missing_runtime():
    return [name for name in ('pandas', 'numpy', 'yfinance') if importlib.util.find_spec(name) is None]


def app_data_dir():
    home = Path.home()
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = home / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', home / '.local' / 'share'))
    return base / 'chart-assistant'


_opener = build_opener(ProxyHandler({}))


def health(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    target = (f'{parts.scheme}://{parts.netloc}/api/package' if parts.scheme and parts.netloc
              else url.rstrip('/') + '/api/package')
    try:
        with _opener.open(target, timeout=1.5) as response:
            data = json.loads(response.read().decode('utf-8'))
        return data.get('app') == 'chart-assistant'
    except Exception:
        return False


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def notify_error(message):
    log('ERROR ' + message)
    for command in (['zenity', '--error', '--title', '초보자 차트 보조기', '--text', message],
                    ['notify-send', '-a', '초보자 차트 보조기', '초보자 차트 보조기', message]):
        if shutil.which(command[0]):
            try:
                subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass


def write_config(config):
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def provider_summary():
    config = read_config()
    return f"일·주·월봉 {config.get('marketProvider', 'yfinance')} · 분봉 {config.get('h4Provider', 'auto')}"


class ServerController:
    def __init__(self, port, live):
        self.port, self.live = port, live
        self.server = None
        self.thread = None
        self.url = None
        self.owned = False

    def start(self):
        import run
        try:
            self.server = run.create_server(self.port, self.live)
            self.owned = True
        except OSError:
            existing = f'http://127.0.0.1:{self.port}'
            if health(existing):
                self.url = existing + '/chart-first.html'
                self.owned = False
                log(f'reusing the running server at {self.url}')
                return self.url
            self.server = run.create_server(0, self.live)
            self.owned = True
        self.url = f'http://127.0.0.1:{self.server.server_port}/chart-first.html'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='chart-qt-server')
        self.thread.start()
        log(f'server started at {self.url}')
        return self.url

    def stop(self):
        if self.server is not None and self.owned:
            try:
                self.server.shutdown()
            except Exception:
                pass
            try:
                self.server.server_close()
            except Exception:
                pass
        self.server = None
        self.thread = None

    def restart(self):
        self.stop()
        return self.start()


def build_icon():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor('#1859C9'))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 13, 13)
    painter.setPen(QPen(QColor('#FFFFFF'), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPolyline([QPoint(12, 43), QPoint(23, 30), QPoint(32, 37), QPoint(41, 20), QPoint(52, 25)])
    painter.end()
    return QIcon(pix)


def run_gui(args, live, url, controller, app, local):
    from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
    from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                                   QFormLayout, QLabel, QMainWindow, QMessageBox, QSystemTrayIcon,
                                   QToolBar, QVBoxLayout)
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    icon = build_icon()
    app.setWindowIcon(icon)

    class HealthBridge(QObject):
        health = Signal(bool)

    class SettingsDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle('공급처 설정')
            self.setMinimumWidth(360)
            config = read_config()
            self.market = QComboBox()
            self.h4 = QComboBox()
            for combo, value in ((self.market, config.get('marketProvider', 'yfinance')),
                                 (self.h4, config.get('h4Provider', 'auto'))):
                combo.addItems(['auto', 'toss', 'yfinance'])
                index = combo.findText(value)
                combo.setCurrentIndex(max(0, index))
            form = QFormLayout(self)
            form.addRow('일·주·월봉 공급처', self.market)
            form.addRow('분봉 공급처', self.h4)
            note = QLabel('기본: 일·주·월봉 Yahoo · 분봉 토스\n'
                          'auto = 지원되는 주식은 토스, 그 외는 Yahoo Finance\n'
                          'toss = 토스 우선 · yfinance = 항상 Yahoo Finance\n'
                          '저장 후 다음 조회부터 적용됩니다.')
            note.setWordWrap(True)
            form.addRow(note)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            form.addRow(buttons)

        def save(self):
            config = read_config()
            config['marketProvider'] = self.market.currentText()
            config['h4Provider'] = self.h4.currentText()
            write_config(config)

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.controller = controller
            self.url = url
            self.failures = 0
            self.restarting = False
            self.settings = QSettings('chart-assistant', 'desktop')
            self.setWindowTitle('초보자 차트 보조기')
            self.setWindowIcon(icon)
            self.resize(1440, 960)
            geometry = self.settings.value('geometry')
            if geometry is not None:
                self.restoreGeometry(geometry)

            data = app_data_dir()
            data.mkdir(parents=True, exist_ok=True)
            self.profile = QWebEngineProfile('chart-assistant', self)
            self.profile.setPersistentStoragePath(str(data / 'web'))
            self.profile.setCachePath(str(data / 'cache'))
            self.view = QWebEngineView(self)
            self.page = QWebEnginePage(self.profile, self.view)
            self.view.setPage(self.page)
            self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            self.setCentralWidget(self.view)
            self.view.load(QUrl(self.url))
            self.view.loadFinished.connect(self.on_load_finished)

            self._build_menu(app)
            self._build_toolbar()
            self.statusBar().showMessage(f'{args.mode} · {provider_summary()} · {self.url}')
            self._build_tray(app)
            self._start_health()
            log(f'window ready · {self.url}')

        def _build_menu(self, app):
            bar = self.menuBar()
            file_menu = bar.addMenu('파일')
            reload_action = QAction('새로고침', self)
            reload_action.setShortcut(QKeySequence('Ctrl+R'))
            reload_action.triggered.connect(self.view.reload)
            file_menu.addAction(reload_action)
            shot = QAction('스크린샷 저장…', self)
            shot.setShortcut(QKeySequence('Ctrl+Shift+S'))
            shot.triggered.connect(self.export_png)
            file_menu.addAction(shot)
            csv_action = QAction('CSV 내보내기…', self)
            csv_action.triggered.connect(self.export_csv)
            file_menu.addAction(csv_action)
            file_menu.addSeparator()
            quit_action = QAction('종료', self)
            quit_action.setShortcut(QKeySequence('Ctrl+Q'))
            quit_action.triggered.connect(self.close)
            file_menu.addAction(quit_action)

            view_menu = bar.addMenu('보기')
            zoom_in = QAction('확대', self)
            zoom_in.setShortcut(QKeySequence('Ctrl+='))
            zoom_in.triggered.connect(lambda: self.view.setZoomFactor(min(3.0, self.view.zoomFactor() * 1.1)))
            view_menu.addAction(zoom_in)
            zoom_out = QAction('축소', self)
            zoom_out.setShortcut(QKeySequence('Ctrl+-'))
            zoom_out.triggered.connect(lambda: self.view.setZoomFactor(max(0.5, self.view.zoomFactor() / 1.1)))
            view_menu.addAction(zoom_out)
            reset_zoom = QAction('원래 크기', self)
            reset_zoom.setShortcut(QKeySequence('Ctrl+0'))
            reset_zoom.triggered.connect(lambda: self.view.setZoomFactor(1.0))
            view_menu.addAction(reset_zoom)
            full = QAction('전체 화면', self)
            full.setShortcut(QKeySequence('F11'))
            full.setCheckable(True)
            full.toggled.connect(lambda checked: self.showFullScreen() if checked else self.showNormal())
            view_menu.addAction(full)
            always = QAction('항상 위', self)
            always.setCheckable(True)
            always.toggled.connect(self.set_always_on_top)
            view_menu.addAction(always)

            tools = bar.addMenu('도구')
            settings_action = QAction('공급처 설정…', self)
            settings_action.triggered.connect(self.open_settings)
            tools.addAction(settings_action)
            tools.addAction('데이터 폴더 열기', self.open_data)
            tools.addAction('로그 열기', self.open_log)
            tools.addAction('서버 재시작', self.restart_server)
            tools.addSeparator()
            tools.addAction('개발자 도구', self.open_devtools)

            help_menu = bar.addMenu('도움말')
            help_menu.addAction('정보', self.show_about)

        def _build_toolbar(self):
            toolbar = QToolBar('주요 도구', self)
            toolbar.setMovable(False)
            self.addToolBar(toolbar)
            reload_action = QAction('새로고침', self)
            reload_action.triggered.connect(self.view.reload)
            toolbar.addAction(reload_action)
            shot = QAction('스크린샷', self)
            shot.triggered.connect(self.export_png)
            toolbar.addAction(shot)
            settings_action = QAction('설정', self)
            settings_action.triggered.connect(self.open_settings)
            toolbar.addAction(settings_action)
            toolbar.addSeparator()
            toolbar.addAction('데이터 폴더', self.open_data)

        def _build_tray(self, app):
            if not QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = None
                return
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip('초보자 차트 보조기')
            from PySide6.QtWidgets import QMenu
            tray_menu = QMenu(self)
            tray_menu.addAction('열기', self.show_normal)
            tray_menu.addAction('숨기기', self.hide)
            tray_menu.addSeparator()
            tray_menu.addAction('종료', self.close)
            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.show()

        def _start_health(self):
            from PySide6.QtCore import QTimer
            self.bridge = HealthBridge()
            self.bridge.health.connect(self.on_health)
            self.health_timer = QTimer(self)
            self.health_timer.timeout.connect(self.check_health)
            self.health_timer.start(5000)
            self.check_health()

        def check_health(self):
            target = self.url
            def probe():
                try:
                    self.bridge.health.emit(health(target))
                except Exception:
                    self.bridge.health.emit(False)
            threading.Thread(target=probe, daemon=True).start()

        def on_health(self, ok):
            if ok:
                self.failures = 0
                self.statusBar().showMessage(f'서버 연결됨 · {provider_summary()} · {self.url}', 2500)
                return
            self.failures += 1
            self.statusBar().showMessage('서버 응답 없음 · 확인 중…')
            if self.failures >= 2 and not self.restarting:
                self.restarting = True
                self.restart_server(auto=True)

        def restart_server(self, auto=False):
            try:
                self.statusBar().showMessage('서버 재시작 중…')
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                self.url = self.controller.restart()
                self.view.load(QUrl(self.url))
                self.failures = 0
                self.statusBar().showMessage(f'서버 재시작 완료 · {self.url}', 4000)
                log(f'server restarted at {self.url}')
            except Exception as exc:
                log(f'server restart failed: {exc!r}')
                self.statusBar().showMessage('서버 재시작 실패 · 로그를 확인하세요')
                if not auto:
                    QMessageBox.critical(self, '서버 재시작 실패', str(exc))
            finally:
                self.restarting = False

        def open_settings(self):
            dialog = SettingsDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                dialog.save()
                self.statusBar().showMessage(f'설정 저장됨 · {provider_summary()} · 다음 조회부터 적용', 4000)

        def open_data(self):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'logs')))

        def open_log(self):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_PATH)))

        def open_devtools(self):
            from PySide6.QtWebEngineWidgets import QWebEngineView
            try:
                dev = QWebEngineView()
                dev.page().setInspectedPage(self.page)
                dev.setWindowTitle('개발자 도구')
                dev.resize(900, 600)
                dev.show()
                self._devtools = dev
            except Exception as exc:
                self.statusBar().showMessage(f'개발자 도구를 열 수 없습니다: {exc}')

        def export_png(self):
            path, _ = QFileDialog.getSaveFileName(self, '차트 스크린샷 저장',
                                                  str(Path.home() / 'chart.png'), 'PNG (*.png)')
            if not path:
                return
            try:
                pix = self.view.grab()
                if pix.save(path):
                    self.statusBar().showMessage(f'저장됨 · {path}', 4000)
                else:
                    QMessageBox.warning(self, '저장 실패', path)
            except Exception as exc:
                QMessageBox.warning(self, '저장 실패', str(exc))

        def export_csv(self):
            script = ("JSON.stringify({symbol:(typeof S!=='undefined'?S.symbol:null),"
                      "tf:(typeof S!=='undefined'?S.tf:null),"
                      "candles:(typeof frameOf==='function'&&frameOf(curSym())?frameOf(curSym()).candles:[])})")
            self.page.runJavaScript(script, self._csv_result)

        def _csv_result(self, result):
            try:
                data = json.loads(result or '{}')
            except (TypeError, ValueError):
                data = {}
            candles = data.get('candles') or []
            if not candles:
                QMessageBox.information(self, 'CSV 내보내기', '현재 화면의 봉 자료를 읽지 못했습니다.')
                return
            symbol = data.get('symbol') or 'chart'
            tf = data.get('tf') or 'D'
            path, _ = QFileDialog.getSaveFileName(self, 'CSV 내보내기',
                                                  str(Path.home() / f'{symbol}-{tf}.csv'), 'CSV (*.csv)')
            if not path:
                return
            try:
                with open(path, 'w', newline='', encoding='utf-8') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(['time', 'open', 'high', 'low', 'close', 'volume'])
                    for candle in candles:
                        writer.writerow([candle.get('time'), candle.get('open'), candle.get('high'),
                                         candle.get('low'), candle.get('close'), candle.get('volume')])
                self.statusBar().showMessage(f'CSV 저장됨 · {path}', 4000)
            except OSError as exc:
                QMessageBox.warning(self, '저장 실패', str(exc))

        def set_always_on_top(self, checked):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
            self.show()

        def on_tray_activated(self, reason):
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self.show_normal()

        def show_normal(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def on_load_finished(self, ok):
            if not ok:
                self.statusBar().showMessage('페이지 로드 실패 · 서버 상태를 확인하세요')

        def show_about(self):
            QMessageBox.about(self, '초보자 차트 보조기',
                              f'버전 {VERSION}\n모드: {args.mode}\n공급처: {provider_summary()}\n'
                              f'{self.url}\n\n로컬 전용 데스크톱 앱입니다. 주문·계좌 기능은 없습니다.')

        def closeEvent(self, event):
            try:
                self.settings.setValue('geometry', self.saveGeometry())
            except Exception:
                pass
            try:
                if self.health_timer.isActive():
                    self.health_timer.stop()
            except Exception:
                pass
            self.controller.stop()
            try:
                if live:
                    import monitor_service
                    if monitor_service._INSTANCE is not None:
                        monitor_service._INSTANCE.close()
            except Exception:
                pass
            event.accept()
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    window = MainWindow()

    def on_new_connection():
        connection = local.nextPendingConnection()
        if connection is None:
            return
        connection.readyRead.connect(lambda: (connection.readAll(), window.show_normal()))
        connection.disconnected.connect(connection.deleteLater)

    local.newConnection.connect(on_new_connection)
    if local.hasPendingConnections():
        on_new_connection()
    window.show()
    return app.exec()


def main():
    parser = argparse.ArgumentParser(description='초보자 차트 보조기 — 데스크톱 앱')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true', help='저장된 자료만 사용')
    mode.add_argument('--live', action='store_true', help='최신조회 서버 사용')
    parser.add_argument('--port', type=int, default=8735)
    parser.add_argument('--no-window', action='store_true', help='창 없이 서버만 실행')
    parsed = parser.parse_args()
    ensure_venv(parsed.offline)
    missing = missing_runtime()
    live = not parsed.offline and not missing
    if parsed.live and missing:
        notify_error('최신조회 의존성 누락: ' + ', '.join(missing) + '\npython setup.py 로 설치하세요.')
        return 2
    if not parsed.no_window and importlib.util.find_spec('PySide6') is None:
        notify_error('PySide6가 필요합니다.\npython setup.py --desktop 로 설치한 뒤 다시 실행하세요.')
        return 2
    parsed.mode = '최신조회' if live else '저장 자료'
    sys.path.insert(0, str(ROOT))

    if parsed.no_window:
        import run
        controller = ServerController(parsed.port, live)
        try:
            url = controller.start()
        except OSError as exc:
            notify_error(f'서버를 시작하지 못했습니다.\n{exc}\n\n로그: {LOG_PATH}')
            return 2
        if live:
            try:
                from monitor_service import start_runtime
                start_runtime()
            except Exception as exc:
                log(f'monitor start failed: {exc!r}')
        print(url, flush=True)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()
        return 0

    from PySide6.QtCore import Qt
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName('초보자 차트 보조기')
    app.setOrganizationName('chart-assistant')
    app.setWindowIcon(build_icon())
    instance_name = 'chart-assistant-' + (str(os.getuid()) if hasattr(os, 'getuid') else os.environ.get('USERNAME', 'user'))
    probe = QLocalSocket()
    probe.connectToServer(instance_name)
    if probe.waitForConnected(300):
        probe.write(b'show')
        probe.flush()
        probe.waitForBytesWritten(300)
        log('another instance is running; asked it to show')
        return 0
    local = QLocalServer()
    QLocalServer.removeServer(instance_name)
    if not local.listen(instance_name):
        log(f'local server listen failed: {local.errorString()}')

    import run
    controller = ServerController(parsed.port, live)
    try:
        url = controller.start()
    except OSError as exc:
        notify_error(f'서버를 시작하지 못했습니다.\n{exc}\n\n로그: {LOG_PATH}')
        return 2
    if live:
        try:
            from monitor_service import start_runtime
            start_runtime()
        except Exception as exc:
            log(f'monitor start failed: {exc!r}')
    try:
        return run_gui(parsed, live, url, controller, app, local)
    except Exception as exc:
        log(f'gui failed: {exc!r}')
        controller.stop()
        raise


if __name__ == '__main__':
    sys.exit(main())
