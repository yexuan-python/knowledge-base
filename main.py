from knowledge_base.bootstrap import create_api_app


app = create_api_app()


def main() -> None:
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=9007, reload=False)


if __name__ == "__main__":
    main()
