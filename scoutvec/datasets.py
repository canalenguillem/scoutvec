# scoutvec/datasets.py
"""Que ligas forman cada espacio vectorial, y donde viven sus ficheros.

Un dataset es un conjunto de ligas de UNA temporada. Los percentiles son
globales dentro del dataset, nunca entre datasets: el percentil 90 de pase
en la Liga F 2023/24 y en La Liga 2015/16 se calculan sobre poblaciones
distintas, asi que mezclarlos en un mismo espacio no significaria nada.
Cada dataset es su propio espacio y se consulta por separado.
"""
from pathlib import Path

DATA = Path("data")


class Dataset:
    def __init__(self, slug, etiqueta, temporada, ligas, nota=""):
        self.slug = slug
        self.etiqueta = etiqueta
        self.temporada = temporada
        self.ligas = ligas           # {nombre: (competition_id, season_id)}
        self.nota = nota

    # Un unico sitio donde se decide como se llaman los ficheros: anadir un
    # dataset no obliga a tocar ninguna ruta a mano.
    @property
    def eventos(self):
        return DATA / f"events_{self.slug}.parquet"

    def eventos_liga(self, liga):
        s = liga.lower().replace(" ", "_").replace(".", "")
        return DATA / f"events_{self.slug}_{s}.parquet"

    @property
    def jugadores(self):
        return Path(f"players_{self.slug}.parquet")

    @property
    def vectores(self):
        return Path(f"vectors_{self.slug}.parquet")

    @property
    def coleccion(self):
        return f"players_{self.slug}"

    def __repr__(self):
        return f"<Dataset {self.slug}: {len(self.ligas)} ligas, {self.temporada}>"


DATASETS = {
    d.slug: d for d in [
        Dataset(
            "men-2015-16", "Men's big four", "2015/16",
            {"La Liga": (11, 27), "Premier": (2, 27),
             "Serie A": (12, 27), "Ligue 1": (7, 27)},
            "Las cuatro grandes ligas masculinas. 5,3M eventos.",
        ),
        Dataset(
            "women-2023-24", "Women's big four", "2023/24",
            {"Liga F": (182, 281), "FA WSL": (37, 281),
             "Frauen Bundesliga": (135, 281), "Serie A Women": (131, 281)},
            "Las cuatro grandes ligas femeninas. Lo mas reciente que "
            "StatsBomb open data ofrece como temporada completa: los datos "
            "masculinos recientes son parciales (la Bundesliga 2023/24 son "
            "34 partidos, todos del Leverkusen).",
        ),
    ]
}

POR_DEFECTO = "men-2015-16"


def get(slug=None):
    slug = slug or POR_DEFECTO
    if slug not in DATASETS:
        raise ValueError(f"dataset desconocido: {slug!r} — "
                         f"validos: {list(DATASETS)}")
    return DATASETS[slug]


def disponibles():
    """Los que ya tienen su vectors.parquet generado."""
    return [d for d in DATASETS.values() if d.vectores.exists()]
