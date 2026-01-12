"""
터미널 색상 출력 유틸리티
ANSI 이스케이프 코드를 사용한 색상 출력
"""

# import * 시 export할 항목 정의
__all__ = [
    'Colors',
    'colorize',
    'print_colored',
    'print_red',
    'print_green',
    'print_yellow',
    'print_blue',
    'print_cyan',
    'print_magenta',
    'print_success',
    'print_error',
    'print_warning',
    'print_info',
    'print_highlight'
]

# ANSI 색상 코드
class Colors:
    """ANSI 색상 코드 클래스"""
    # 텍스트 색상
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # 밝은 색상
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # 배경 색상
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # 스타일
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    STRIKETHROUGH = '\033[9m'
    
    # 리셋
    RESET = '\033[0m'
    END = '\033[0m'


def colorize(text: str, color: str = '', style: str = '') -> str:
    """
    텍스트에 색상과 스타일 적용
    
    Args:
        text: 색상을 적용할 텍스트
        color: 색상 코드 (Colors 클래스의 상수)
        style: 스타일 코드 (Colors 클래스의 스타일 상수)
        
    Returns:
        색상이 적용된 텍스트
    """
    return f"{style}{color}{text}{Colors.RESET}"


def print_colored(text: str, color: str = '', style: str = '', end: str = '\n'):
    """
    색상이 적용된 텍스트를 출력
    
    Args:
        text: 출력할 텍스트
        color: 색상 코드
        style: 스타일 코드
        end: 끝 문자 (기본값: 줄바꿈)
    """
    print(colorize(text, color, style), end=end)


# 편의 함수들
def print_red(text: str, bold: bool = False):
    """빨간색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.RED, style)


def print_green(text: str, bold: bool = False):
    """초록색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.GREEN, style)


def print_yellow(text: str, bold: bool = False):
    """노란색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.YELLOW, style)


def print_blue(text: str, bold: bool = False):
    """파란색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.BLUE, style)


def print_cyan(text: str, bold: bool = False):
    """청록색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.CYAN, style)


def print_magenta(text: str, bold: bool = False):
    """자홍색으로 출력"""
    style = Colors.BOLD if bold else ''
    print_colored(text, Colors.MAGENTA, style)


def print_success(text: str):
    """성공 메시지 출력 (초록색, 굵게)"""
    print_colored(text, Colors.GREEN, Colors.BOLD)


def print_error(text: str):
    """에러 메시지 출력 (빨간색, 굵게)"""
    print_colored(text, Colors.RED, Colors.BOLD)


def print_warning(text: str):
    """경고 메시지 출력 (노란색, 굵게)"""
    print_colored(text, Colors.YELLOW, Colors.BOLD)


def print_info(text: str):
    """정보 메시지 출력 (파란색)"""
    print_colored(text, Colors.BLUE)


def print_highlight(text: str):
    """강조 메시지 출력 (청록색, 굵게)"""
    print_colored(text, Colors.CYAN, Colors.BOLD)


# 사용 예제
if __name__ == "__main__":
    print("=== 터미널 색상 출력 예제 ===\n")
    
    print_red("빨간색 텍스트")
    print_green("초록색 텍스트")
    print_yellow("노란색 텍스트")
    print_blue("파란색 텍스트")
    print_cyan("청록색 텍스트")
    print_magenta("자홍색 텍스트")
    
    print()
    print_success("✓ 성공 메시지")
    print_error("✗ 에러 메시지")
    print_warning("⚠ 경고 메시지")
    print_info("ℹ 정보 메시지")
    print_highlight("★ 강조 메시지")
    
    print()
    print(colorize("굵은 빨간색 텍스트", Colors.RED, Colors.BOLD))
    print(colorize("밑줄 파란색 텍스트", Colors.BLUE, Colors.UNDERLINE))
    print(colorize("반전된 초록색 텍스트", Colors.GREEN, Colors.REVERSE))
    
    print()
    # 복합 사용
    print(f"{Colors.BOLD}{Colors.GREEN}진입가: ${1000:,.2f}{Colors.RESET}")
    print(f"{Colors.RED}손절가: ${950:,.2f}{Colors.RESET}")
    print(f"{Colors.GREEN}익절가: ${1050:,.2f}{Colors.RESET}")

