"""图形验证码生成。

用 Pillow 手绘而不是装第三方验证码库：
市面库的默认尺寸（通常是 160x60 或 120x40）与前端 `<img>` 的固定容器 240x80 不匹配，
拉伸后变形。这里按原尺寸重绘，样式上也保留了 Go 版的观感（浅色底 + 彩色字符 + 干扰线）。
"""

import base64
import io
import random
import secrets
from pathlib import Path

from anyio import to_thread
from PIL import Image, ImageDraw, ImageFont

# 候选字体路径（Windows 优先，Linux 兜底）。
# 都不存在时退回 Pillow 的内置位图字体（放大会糊，但不会崩）。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# 字符颜色池：深色系，保证在白底上清晰
_CHAR_COLORS = (
    (32, 62, 128),
    (140, 40, 40),
    (30, 110, 70),
    (110, 60, 20),
    (80, 40, 120),
)


class ImageCaptchaGenerator:
    """6 位数字图形验证码。

    Pillow 全是同步 CPU 操作（一张图约 2-5 ms，编解码另算），
    直接放在协程里会阻塞事件循环，所以统一丢线程池。
    """

    WIDTH = 240
    HEIGHT = 80
    LENGTH = 6
    # 字号：80 高的画布用 52px，视觉上占约 2/3，与 Go 版接近
    FONT_SIZE = 52
    LINE_COUNT = 3
    DOT_COUNT = 120

    async def generate(self) -> tuple[str, str]:
        """生成一组验证码。

        Returns:
            `(answer, data_uri)`：
            - `answer` 是 6 位数字字符串，写进缓存供比对
            - `data_uri` 是 `data:image/png;base64,...`，可直接塞进 `<img src>`
        """
        code = "".join(secrets.choice("0123456789") for _ in range(self.LENGTH))
        # 绘制与编码都是 CPU 密集，丢线程池避免卡住其他请求
        data_uri = await to_thread.run_sync(self._render, code)
        return code, data_uri

    def _render(self, code: str) -> str:
        """把验证码画成 PNG 并转成 data URI。

        Args:
            code: 6 位数字。

        Returns:
            带 `data:image/png;base64,` 前缀的字符串。
        """
        image = Image.new("RGB", (self.WIDTH, self.HEIGHT), (247, 249, 252))
        draw = ImageDraw.Draw(image)
        font = self._load_font()

        # 干扰线：画在字符之前，避免盖住数字
        for _ in range(self.LINE_COUNT):
            draw.line(
                (
                    random.randint(0, self.WIDTH),
                    random.randint(0, self.HEIGHT),
                    random.randint(0, self.WIDTH),
                    random.randint(0, self.HEIGHT),
                ),
                fill=self._random_light_color(),
                width=2,
            )

        # 逐字符绘制：每个字符独立颜色和上下抖动，防 OCR 也更好看
        slot_width = self.WIDTH // self.LENGTH
        for index, char in enumerate(code):
            color = random.choice(_CHAR_COLORS)
            # 用 textbbox 拿到实际宽高，才能精确居中
            left, top, right, bottom = draw.textbbox((0, 0), char, font=font)
            char_w = right - left
            char_h = bottom - top
            x = index * slot_width + (slot_width - char_w) // 2
            # 垂直抖动 ±8px，避免字符排成一条直线
            y = (self.HEIGHT - char_h) // 2 - top + random.randint(-8, 8)
            draw.text((x, y), char, font=font, fill=color)

        # 干扰点
        for _ in range(self.DOT_COUNT):
            draw.point(
                (random.randint(0, self.WIDTH), random.randint(0, self.HEIGHT)),
                fill=self._random_light_color(),
            )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _load_font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """加载字体。

        找不到任何 TTF 时退回 Pillow 内置字体。内置字体不支持 size 参数的老版本
        会抛 TypeError，这里一并兜住 —— 验证码糊一点总比 500 强。

        Returns:
            字体对象。
        """
        for path in _FONT_CANDIDATES:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, self.FONT_SIZE)
                except OSError:
                    continue  # 文件存在但损坏，换下一个
        try:
            return ImageFont.load_default(size=self.FONT_SIZE)
        except TypeError:
            return ImageFont.load_default()

    @staticmethod
    def _random_light_color() -> tuple[int, int, int]:
        """生成浅色（干扰元素用，不能盖住数字）。"""
        return (
            random.randint(150, 210),
            random.randint(150, 210),
            random.randint(150, 210),
        )
