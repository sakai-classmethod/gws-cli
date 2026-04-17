import typer

from gws_cli.calendar import app as calendar_app
from gws_cli.docs import app as docs_app
from gws_cli.drive import app as drive_app

app = typer.Typer()
app.add_typer(calendar_app, name="calendar")
app.add_typer(docs_app, name="docs")
app.add_typer(drive_app, name="drive")

if __name__ == "__main__":
    app()
