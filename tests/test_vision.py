from PIL import Image

from reverse1999_agent.vision import orange_action_center, screen_change_ratio


def test_identical_images_have_no_change() -> None:
    image = Image.new("RGB", (100, 100), "black")
    assert screen_change_ratio(image, image.copy()) == 0.0


def test_different_images_have_change() -> None:
    first = Image.new("RGB", (100, 100), "black")
    second = Image.new("RGB", (100, 100), "white")
    assert screen_change_ratio(first, second) == 1.0


def test_orange_action_center_finds_large_button() -> None:
    image = Image.new("RGB", (1920, 1080), "black")
    pixels = image.load()
    for y in range(510, 611):
        for x in range(1105, 1359):
            pixels[x, y] = (198, 86, 32)
    center = orange_action_center(image)
    assert center is not None
    assert abs(center[0] - 1232) <= 2
    assert abs(center[1] - 560) <= 2


def test_orange_action_center_rejects_full_screen_orange_background() -> None:
    image = Image.new("RGB", (1920, 1080), (198, 86, 32))
    assert orange_action_center(image) is None
