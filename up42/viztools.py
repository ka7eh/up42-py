"""
Visualization tools available in various objects
"""

from typing import Tuple, List, Union, Dict
import math
from pathlib import Path
import warnings

import numpy as np
from shapely.geometry import box
import geopandas as gpd
from geopandas import GeoDataFrame
import matplotlib.pyplot as plt
import rasterio
from rasterio.plot import show
from rasterio.vrt import WarpedVRT
import folium
from folium.plugins import Draw

from up42.utils import (
    get_logger,
)


try:
    from IPython import get_ipython

    get_ipython().run_line_magic("matplotlib", "inline")
except (ImportError, AttributeError):
    # No Ipython installed, Installed but run in shell
    pass


logger = get_logger(__name__)


# pylint: disable=no-member, duplicate-code
class VizTools:
    def __init__(self):
        """
        Visualization functionality
        """
        self.quicklooks = None
        self.results = None

    def plot_results(
        self,
        figsize: Tuple[int, int] = (14, 8),
        filepaths: Union[List[Union[str, Path]], Dict] = None,
        titles: List[str] = None,
        # pylint: disable=dangerous-default-value
        plot_file_format: List[str] = [".tif"],
    ) -> None:
        """
        Plots image data (quicklooks or results)

        Args:
            plot_file_format: List of accepted image file formats e.g. [".tif"]
            figsize: matplotlib figure size.
            filepaths: Paths to images to plot. Optional, by default picks up the last
                downloaded results.
            titles: Optional list of titles for the subplots.

        """
        if filepaths is None:
            if self.results is None:
                raise ValueError("You first need to download the results!")
            filepaths = self.results
            # Unpack results path dict in case of jobcollection.
            if isinstance(filepaths, dict):
                filepaths_lists = list(filepaths.values())
                filepaths = [item for sublist in filepaths_lists for item in sublist]

        if not isinstance(filepaths, list):
            filepaths = [filepaths]  # type: ignore
        filepaths = [Path(path) for path in filepaths]

        imagepaths = [
            path for path in filepaths if str(path.suffix) in plot_file_format  # type: ignore
        ]
        if not imagepaths:
            raise ValueError(
                f"This function only plots files of format {plot_file_format}."
            )

        if not titles:
            titles = [Path(fp).stem for fp in imagepaths]
        if not isinstance(titles, list):
            titles = [titles]  # type: ignore

        if len(imagepaths) < 2:
            nrows, ncols = 1, 1
        else:
            ncols = 3
            nrows = int(math.ceil(len(imagepaths) / float(ncols)))

        _, axs = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize)
        if len(imagepaths) > 1:
            axs = axs.ravel()
        else:
            axs = [axs]

        for idx, (fp, title) in enumerate(zip(imagepaths, titles)):
            with rasterio.open(fp) as src:
                img_array = src.read()[:3, :, :]
                # TODO: Handle more band configurations.
                # TODO: add histogram equalization?
                show(
                    img_array,
                    transform=src.transform,
                    title=title,
                    ax=axs[idx],
                    aspect="auto",
                )
            axs[idx].set_axis_off()
        plt.axis("off")
        plt.tight_layout()
        plt.show()

    def plot_quicklooks(
        self,
        figsize: Tuple[int, int] = (8, 8),
        filepaths: List = None,
        titles: List[str] = None,
    ) -> None:
        """
        Plots the downloaded quicklooks (filepaths saved to self.quicklooks of the
        respective object, e.g. job, catalog).

        Args:
                figsize: matplotlib figure size.
                filepaths: Paths to images to plot. Optional, by default picks up the last
                        downloaded results.
                titles: List of titles for the subplots, optional.

        """
        if filepaths is None:
            if self.quicklooks is None:
                raise ValueError("You first need to download the quicklooks!")
            filepaths = self.quicklooks

        warnings.filterwarnings(
            "ignore", category=rasterio.errors.NotGeoreferencedWarning
        )
        self.plot_results(
            plot_file_format=[".jpg", ".jpeg", ".png"],
            figsize=figsize,
            filepaths=filepaths,
            titles=titles,
        )

    @staticmethod
    def _map_images(
        plot_file_format: List[str],
        result_df: GeoDataFrame,
        filepaths,
        aoi=None,
        show_images=True,
        show_features=False,
        name_column: str = "id",
        save_html: Path = None,
    ) -> folium.Map:
        """
        Displays data.json, and if available, one or multiple results geotiffs.
        Args:
            plot_file_format: List of accepted image file formats e.g. [".png"]
            result_df: GeoDataFrame of scenes, results of catalog.search()
            aoi: GeoDataFrame of aoi
            filepaths: Paths to images to plot. Optional, by default picks up the last
                downloaded results.
            show_images: Shows images if True (default).
            show_features: Show features if True. For quicklooks maps is set to False.
            name_column: Name of the feature property that provides the Feature/Layer name.
            save_html: The path for saving folium map as html file. With default None, no file is saved.
        """

        centroid = box(*result_df.total_bounds).centroid
        m = folium_base_map(
            lat=centroid.y,
            lon=centroid.x,
        )

        df_bounds = result_df.bounds
        list_bounds = df_bounds.values.tolist()
        raster_filepaths = [
            path for path in filepaths if Path(path).suffix in plot_file_format
        ]

        try:
            feature_names = result_df[name_column].to_list()
        except KeyError:
            feature_names = [""] * len(result_df.index)

        if aoi is not None:
            folium.GeoJson(
                aoi,
                name="geojson",
                style_function=_style_function,
                highlight_function=_highlight_function,
            ).add_to(m)

        if show_features:
            for idx, row in result_df.iterrows():  # type: ignore
                try:
                    feature_name = row.loc[name_column]
                except KeyError:
                    feature_name = ""
                layer_name = f"Feature {idx + 1} - {feature_name}"
                f = folium.GeoJson(
                    row["geometry"],
                    name=layer_name,
                    style_function=_style_function,
                    highlight_function=_highlight_function,
                )
                folium.Popup(
                    f"{layer_name}: {row.drop('geometry', axis=0).to_json()}"
                ).add_to(f)
                f.add_to(m)

        if show_images and raster_filepaths:
            for idx, (raster_fp, feature_name) in enumerate(
                zip(raster_filepaths, feature_names)
            ):
                with rasterio.open(raster_fp) as src:
                    if src.meta["crs"] is None:
                        dst_array = src.read()[:3, :, :]
                        minx, miny, maxx, maxy = list_bounds[idx]
                    else:
                        # Folium requires 4326, streaming blocks are 3857
                        with WarpedVRT(src, crs="EPSG:4326") as vrt:
                            dst_array = vrt.read()[:3, :, :]
                            minx, miny, maxx, maxy = vrt.bounds

                m.add_child(
                    folium.raster_layers.ImageOverlay(
                        np.moveaxis(np.stack(dst_array), 0, 2),
                        bounds=[[miny, minx], [maxy, maxx]],  # different order.
                        name=f"Image {idx + 1} - {feature_name}",
                    )
                )

        # Collapse layer control with too many features.
        collapsed = bool(result_df.shape[0] > 4)
        folium.LayerControl(position="bottomleft", collapsed=collapsed).add_to(m)

        if save_html:
            save_html = Path(save_html)
            if not save_html.exists():
                save_html.mkdir(parents=True, exist_ok=True)
            filepath = save_html / "final_map.html"
            with filepath.open("w") as f:
                f.write(m._repr_html_())
        return m

    def map_results(
        self, show_images: bool = True, name_column: str = "uid", save_html=None
    ) -> folium.Map:
        """
        Displays data.json, and if available, one or multiple results geotiffs.
        Args:
            show_images: Shows images if True (default), only features if False.
            name_column: Name of the feature property that provides the Feature/Layer name.
            save_html: The path for saving folium map as html file. With default None, no file is saved.
        """
        if self.results is None:
            raise ValueError(
                "You first need to download the results via job.download_results()!"
            )

        # Add features to map.
        # Some blocks store vector results in an additional geojson file.
        # pylint: disable=not-an-iterable
        json_fp = [fp for fp in self.results if fp.endswith(".geojson")]
        if json_fp:
            json_fp = json_fp[0]
        else:
            # pylint: disable=not-an-iterable
            json_fp = [fp for fp in self.results if fp.endswith(".json")][0]
        df: GeoDataFrame = gpd.read_file(json_fp)

        # Add image to map.
        m = self._map_images(
            plot_file_format=[".tif"],
            result_df=df,
            filepaths=self.results,
            aoi=None,
            show_images=show_images,
            show_features=True,
            name_column=name_column,
            save_html=save_html,
        )
        return m

    def map_quicklooks(
        self,
        scenes: GeoDataFrame,
        aoi: GeoDataFrame = None,
        filepaths: List = None,
        name_column: str = "id",
        save_html: Path = None,
    ) -> folium.Map:
        """
        TODO: Currently only implemented for catalog!

        Plots the downloaded quicklooks (filepaths saved to self.quicklooks of the
        respective object, e.g. job, catalog).

        Args:
                scenes: GeoDataFrame of scenes, results of catalog.search()
                aoi: GeoDataFrame of aoi.
                filepaths: Paths to images to plot. Optional, by default picks up the last
                        downloaded results.
                name_column: Name of the feature property that provides the Feature/Layer name.
                save_html: The path for saving folium map as html file. With default None, no file is saved.
        """
        if filepaths is None:
            if self.quicklooks is None:
                raise ValueError("You first need to download the quicklooks!")
            filepaths = self.quicklooks

        warnings.filterwarnings(
            "ignore", category=rasterio.errors.NotGeoreferencedWarning
        )
        m = self._map_images(
            plot_file_format=[".jpg", ".jpeg", ".png"],
            result_df=scenes,
            filepaths=filepaths,
            aoi=aoi,
            name_column=name_column,
            save_html=save_html,
        )
        return m

    @staticmethod
    def plot_coverage(
        scenes: GeoDataFrame,
        aoi: GeoDataFrame = None,
        legend_column: str = "scene_id",
        figsize=(12, 16),
    ) -> None:
        """
        Plots a coverage map of a dataframe with geometries e.g. the results of catalog.search())
        Args:
                scenes: GeoDataFrame of scenes, results of catalog.search()
                aoi: GeoDataFrame of aoi.
                legend_column: Dataframe column set to legend, default is "scene_id".
                        Legend entries are sorted and this determines plotting order.
                figsize: Matplotlib figure size.
        """
        if legend_column not in scenes.columns:
            legend_column = None  # type: ignore
            logger.info(
                "Given legend_column name not in scene dataframe, "
                "plotting without legend."
            )

        ax = scenes.plot(
            legend_column,
            categorical=True,
            figsize=figsize,
            cmap="Set3",
            legend=True,
            alpha=0.7,
            legend_kwds=dict(loc="upper left", bbox_to_anchor=(1, 1)),
        )
        if aoi is not None:
            aoi.plot(color="r", ax=ax, fc="None", edgecolor="r", lw=1)
        ax.set_axis_off()
        plt.show()


def folium_base_map(
    lat: float = 52.49190032214706,
    lon: float = 13.39117252959244,
    zoom_start: int = 14,
    width_percent: str = "95%",
    layer_control=False,
) -> folium.Map:
    """Provides a folium map with basic features and UP42 logo."""
    mapfigure = folium.Figure(width=width_percent)
    m = folium.Map(location=[lat, lon], zoom_start=zoom_start, crs="EPSG3857").add_to(
        mapfigure
    )

    tiles = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery"
        "/MapServer/tile/{z}/{y}/{x}.png"
    )
    attr = (
        "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, "
        "AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the "
        "GIS User Community"
    )
    folium.TileLayer(tiles=tiles, attr=attr, name="Satellite - ESRI").add_to(m)

    formatter = "function(num) {return L.Util.formatNum(num, 4) + ' ';};"
    folium.plugins.MousePosition(
        position="bottomright",
        separator=" | ",
        empty_string="NaN",
        lng_first=True,
        num_digits=20,
        prefix="lon/lat:",
        lat_formatter=formatter,
        lng_formatter=formatter,
    ).add_to(m)

    folium.plugins.MiniMap(
        tile_layer="OpenStreetMap", position="bottomright", zoom_level_offset=-6
    ).add_to(m)
    folium.plugins.Fullscreen().add_to(m)
    folium.plugins.FloatImage(
        image="https://cdn-images-1.medium.com/max/140/1*XJ_B7ur_c8bYKniXpKVpWg@2x.png",
        bottom=90,
        left=88,
    ).add_to(m)

    if layer_control:
        folium.LayerControl(position="bottomleft", collapsed=False, zindex=100).add_to(
            m
        )
        # If adding additional layers outside of the folium base map function, don't
        # use this one here. Causes an empty map.
    return m


def _style_function(_):
    return {
        "fillColor": "#5288c4",
        "color": "blue",
        "weight": 2.5,
        "dashArray": "5, 5",
    }


def _highlight_function(_):
    return {
        "fillColor": "#ffaf00",
        "color": "red",
        "weight": 3.5,
        "dashArray": "5, 5",
    }


class DrawFoliumOverride(Draw):
    def render(self, **kwargs):
        # pylint: disable=import-outside-toplevel
        from branca.element import CssLink, Element, Figure, JavascriptLink

        super(DrawFoliumOverride, self).render(**kwargs)

        figure = self.get_root()
        assert isinstance(figure, Figure), (
            "You cannot render this Element " "if it is not in a Figure."
        )

        figure.header.add_child(
            JavascriptLink(
                "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/"
                "leaflet.draw.js"
            )
        )  # noqa
        figure.header.add_child(
            CssLink(
                "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/"
                "leaflet.draw.css"
            )
        )  # noqa

        export_style = """
            <style>
                #export {
                    position: absolute;
                    top: 270px;
                    left: 11px;
                    z-index: 999;
                    padding: 6px;
                    border-radius: 3px;
                    box-sizing: border-box;
                    color: #333;
                    background-color: #fff;
                    border: 2px solid rgba(0,0,0,0.5);
                    box-shadow: None;
                    font-family: 'Helvetica Neue';
                    cursor: pointer;
                    font-size: 17px;
                    text-decoration: none;
                    text-align: center;
                    font-weight: bold;
                }
            </style>
        """
        # TODO: How to change hover color?
        export_button = """<a href='#' id='export'>Export as<br/>GeoJson</a>"""
        if self.export:
            figure.header.add_child(Element(export_style), name="export")
            figure.html.add_child(Element(export_button), name="export_button")