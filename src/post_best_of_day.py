"""Точка входа: находит лучшее видео за день и постит ссылку на него в Reddit."""
from dotenv import load_dotenv

from find_best_video import find_best_recent_video
from reddit_post import post_link

load_dotenv()


def run() -> None:
    best = find_best_recent_video()
    if not best:
        print("Нет видео за последние 26 часов, пропускаю.")
        return

    print(f"Лучшее видео: {best['title']} ({best['view_count']} просмотров)")
    post_link(title=best["title"], url=best["url"])


if __name__ == "__main__":
    run()
