import typer

from gws_cli.calendar import app as calendar_app
from gws_cli.docs import app as docs_app

app = typer.Typer()
app.add_typer(calendar_app, name="calendar")
app.add_typer(docs_app, name="docs")

if __name__ == "__main__":
    app()
