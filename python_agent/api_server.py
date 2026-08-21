"""兼容启动器；正式 HTTP 实现位于 after_sales_agent.interface。"""

from after_sales_agent.interface.http_server import main


if __name__ == "__main__":
    main()
