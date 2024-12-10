import certifi
import json
import ssl 
import asyncio
import websockets
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QLineEdit, QPushButton, QTextEdit, QLabel, QFrame)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QColor, QPalette
from datetime import datetime
import sys
import os

# 유니코드 및 기타 상수
F = "\x0c"
ESC = "\x1b\t"
SEPARATOR = "+" + "-" * 70 + "+"

def get_executable_dir():
    """실행 파일 또는 스크립트가 있는 디렉토리 경로를 반환합니다."""
    if getattr(sys, 'frozen', False):
        # exe로 실행될 때
        return os.path.dirname(sys.executable)
    else:
        # 스크립트로 실행될 때
        return os.path.dirname(os.path.abspath(__file__))

class ChatWorker(QThread):
    
    message_received = pyqtSignal(str)
    connection_status = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = True
        self.log_file = None
        # 실행 파일이 있는 디렉토리에 'chat_logs' 폴더 생성
        self.log_directory = os.path.join(get_executable_dir(), "chat_logs")

    def run(self):
        asyncio.run(self.connect_to_chat())

    # ChatWorker 클래스의 setup_log_file 메서드에 로깅 추가
    def setup_log_file(self, title):
        try:
            print(f"현재 작업 디렉토리: {os.getcwd()}")  # 디버깅 출력 추가
            
            # 로그 디렉토리 생성
            if not os.path.exists(self.log_directory):
                os.makedirs(self.log_directory)
                print(f"디렉토리 생성: {self.log_directory}")
            
            # 파일명에 사용할 수 없는 문자 제거
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            current_time = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 파일명 생성
            filename = f"{current_time}_{safe_title}.txt"
            self.log_file = os.path.join(self.log_directory, filename)
            print(f"로그 파일 생성 시도: {self.log_file}")
            
            # 파일 헤더 작성
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"방송 제목: {title}\n")
                f.write(f"기록 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("-" * 80 + "\n\n")
                print("로그 파일 헤더 작성 완료")
                
        except Exception as e:
            print(f"로그 파일 설정 오류 (상세): {str(e)}")
            self.connection_status.emit(f"로그 파일 설정 오류: {str(e)}")

    async def connect_to_chat(self):
        try:
            BNO, BID = self.url.split('/')[-1], self.url.split('/')[-2]
            result = get_player_live(BNO, BID)
            if result is None:
                self.connection_status.emit("채팅 정보를 가져오는데 실패했습니다.")
                return
                
            CHDOMAIN, CHATNO, FTK, TITLE, BJID, CHPT = result
            
            # 로그 파일 설정
            self.setup_log_file(TITLE)
            
            self.connection_status.emit(
                f"방송 제목: {TITLE}\n"
                f"BJ ID: {BJID}\n"
                f"채팅 저장 위치: {self.log_file}\n"
                f"연결 중..."
            )

            ssl_context = create_ssl_context()
            
            async with websockets.connect(
                f"wss://{CHDOMAIN}:{CHPT}/Websocket/{BID}",
                subprotocols=['chat'],
                ssl=ssl_context,
                ping_interval=None
            ) as websocket:
                CONNECT_PACKET = f'{ESC}000100000600{F*3}16{F}'
                JOIN_PACKET = f'{ESC}0002{calculate_byte_size(CHATNO):06}00{F}{CHATNO}{F*5}'
                PING_PACKET = f'{ESC}000000000100{F}'

                await websocket.send(CONNECT_PACKET)
                self.connection_status.emit("채팅방 연결 성공!")
                await asyncio.sleep(2)
                await websocket.send(JOIN_PACKET)

                async def ping():
                    while self.running:
                        await asyncio.sleep(60)
                        try:
                            await websocket.send(PING_PACKET)
                        except:
                            break
                
                async def receive_messages():
                    while self.running:
                        try:
                            data = await websocket.recv()
                            self.decode_message(data)
                        except websockets.exceptions.ConnectionClosed:
                            self.connection_status.emit("연결이 종료되었습니다.")
                            break
                        except Exception as e:
                            self.connection_status.emit(f"에러 발생: {str(e)}")
                            break
                
                await asyncio.gather(receive_messages(), ping())

        except Exception as e:
            self.connection_status.emit(f"연결 오류: {str(e)}")

    def decode_message(self, bytes):
        try:
            parts = bytes.split(b'\x0c')
            messages = [part.decode('utf-8') for part in parts]
            
            if len(messages) > 6:
                user_id = messages[2] if len(messages) > 2 else "unknown"
                comment = messages[1] if len(messages) > 1 else "no message"
                user_nickname = messages[6] if len(messages) > 6 else "unknown"
                
                if comment not in ['-1', '1'] and '|' not in comment and 'fw=' not in comment:
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    chat_message = f"[{current_time}] {user_nickname}[{user_id}] - {comment}"
                    
                    # 채팅을 파일에 저장
                    if self.log_file:
                        try:
                            with open(self.log_file, 'a', encoding='utf-8') as f:
                                f.write(chat_message + '\n')
                        except Exception as e:
                            self.connection_status.emit(f"채팅 저장 오류: {str(e)}")
                    
                    self.message_received.emit(chat_message)
        except Exception as e:
            self.connection_status.emit(f"메시지 디코딩 오류: {str(e)}")

    def stop(self):
        self.running = False
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n기록 종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            except Exception as e:
                self.connection_status.emit(f"로그 파일 종료 오류: {str(e)}")

class CustomTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #404040;
                border-radius: 8px;
                padding: 10px;
            }
            QScrollBar:vertical {
                border: none;
                background: #2b2b2b;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #404040;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

class ModernButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            QPushButton {
                background-color: #5c6bc0;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7986cb;
            }
            QPushButton:pressed {
                background-color: #3f51b5;
            }
            QPushButton:disabled {
                background-color: #424242;
                color: #808080;
            }
        """)

class ModernLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QLineEdit {
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 2px solid #404040;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #5c6bc0;
            }
        """)

class AfreecaTVChatViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.chat_worker = None
        # 실행 파일이 있는 디렉토리에 settings.json 파일 생성
        self.settings_file = os.path.join(get_executable_dir(), "settings.json")
        self.load_settings()
        self.init_ui()

    def load_settings(self):
        """저장된 설정을 불러옵니다."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.last_url = settings.get('last_url', '')
            else:
                self.last_url = ''
        except Exception as e:
            print(f"설정 불러오기 오류: {e}")
            self.last_url = ''

    def save_settings(self):
        """현재 설정을 저장합니다."""
        try:
            settings = {
                'last_url': self.url_input.text().strip()
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"설정 저장 오류: {e}")

    def closeEvent(self, event):
        """프로그램 종료 시 호출되는 이벤트"""
        # 연결이 활성화되어 있다면 종료
        if self.chat_worker is not None:
            self.chat_worker.stop()
            self.chat_worker = None

        # 현재 설정 저장
        self.save_settings()
        event.accept()

    def toggle_connection(self):
        if self.chat_worker is None:
            url = self.url_input.text().strip()
            if not url:
                self.status_display.append("URL을 입력해주세요.")
                return

            # URL이 변경되었다면 저장
            if url != self.last_url:
                self.last_url = url
                self.save_settings()

            print("채팅 연결 시작...")  # 디버깅 메시지 추가
            self.chat_worker = ChatWorker(url)
            self.chat_worker.message_received.connect(self.update_chat)
            self.chat_worker.connection_status.connect(self.update_status)
            self.chat_worker.start()
            self.connect_button.setText('연결 종료')
            self.connect_button.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                }
                QPushButton:hover {
                    background-color: #e57373;
                }
                QPushButton:pressed {
                    background-color: #d32f2f;
                }
            """)
        else:
            print("채팅 연결 종료...")  # 디버깅 메시지 추가
            self.chat_worker.stop()
            self.chat_worker = None
            self.connect_button.setText('연결')
            self.connect_button.setStyleSheet(ModernButton.styleSheet(self))
            self.status_display.append("연결이 종료되었습니다.")

    def init_ui(self):
        self.setWindowTitle('AfreecaTV Chat Viewer')
        self.setGeometry(100, 100, 500, 800)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QLabel {
                color: #e0e0e0;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 5px;
            }
        """)

        # 메인 위젯 및 레이아웃
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 상단 타이틀
        title_label = QLabel('AfreecaTV Chat Viewer')
        title_label.setStyleSheet("""
            QLabel {
                color: #e0e0e0;
                font-size: 24px;
                font-weight: bold;
                padding: 10px 0;
            }
        """)
        layout.addWidget(title_label)

        # URL 입력 섹션
        url_section = QFrame()
        url_section.setStyleSheet("""
            QFrame {
                background-color: #252525;
                border-radius: 10px;
                padding: 15px;
            }
        """)
        url_layout = QVBoxLayout(url_section)
        
        url_label = QLabel('방송 URL을 입력하세요')
        self.url_input = ModernLineEdit()
        self.url_input.setPlaceholderText('https://play.afreecatv.com/[BJ_ID]/[BNO]')
        
        # 여기로 이동: 저장된 URL 설정
        if hasattr(self, 'last_url') and self.last_url:
            self.url_input.setText(self.last_url)
        
        self.connect_button = ModernButton('연결')
        self.connect_button.clicked.connect(self.toggle_connection)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.connect_button)
        layout.addWidget(url_section)

        # 상태 표시 섹션
        status_label = QLabel('상태')
        self.status_display = CustomTextEdit()
        self.status_display.setMaximumHeight(100)
        self.status_display.setReadOnly(True)
        layout.addWidget(status_label)
        layout.addWidget(self.status_display)

        # 채팅 표시 섹션
        chat_label = QLabel('채팅')
        self.chat_display = CustomTextEdit()
        self.chat_display.setReadOnly(True)
        layout.addWidget(chat_label)
        layout.addWidget(self.chat_display)

        main_widget.setLayout(layout)

    def update_chat(self, message):
        self.chat_display.append(message)
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    def update_status(self, status):
        self.status_display.append(status)
        self.status_display.verticalScrollBar().setValue(
            self.status_display.verticalScrollBar().maximum()
        )

    

def create_ssl_context():
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context

def calculate_byte_size(string):
    return len(string.encode('utf-8')) + 6

def get_player_live(bno, bid):
    url = 'https://live.afreecatv.com/afreeca/player_live_api.php'
    data = {
        'bid': bid,
        'bno': bno,
        'type': 'live',
        'confirm_adult': 'false',
        'player_type': 'html5',
        'mode': 'landing',
        'from_api': '0',
        'pwd': '',
        'stream_type': 'common',
        'quality': 'HD'
    }

    try:
        response = requests.post(f'{url}?bjid={bid}', data=data)
        response.raise_for_status()
        res = response.json()

        CHDOMAIN = res["CHANNEL"]["CHDOMAIN"].lower()
        CHATNO = res["CHANNEL"]["CHATNO"]
        FTK = res["CHANNEL"]["FTK"]
        TITLE = res["CHANNEL"]["TITLE"]
        BJID = res["CHANNEL"]["BJID"]
        CHPT = str(int(res["CHANNEL"]["CHPT"]) + 1)

        return CHDOMAIN, CHATNO, FTK, TITLE, BJID, CHPT

    except requests.RequestException as e:
        print(f"  ERROR: API 요청 중 오류 발생: {e}")
        return None
    except KeyError as e:
        print(f"  ERROR: 응답에서 필요한 데이터를 찾을 수 없습니다: {e}")
        return None

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    viewer = AfreecaTVChatViewer()
    viewer.show()
    sys.exit(app.exec())