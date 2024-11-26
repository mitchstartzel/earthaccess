import logging
import shutil
from pathlib import Path
from typing import TypedDict

import earthaccess
import pytest
from earthaccess import Auth, DataGranules, Store

from .sample import get_sample_granules

logger = logging.getLogger(__name__)


class TestParam(TypedDict):
    provider_name: str

    # How many of the top collections we will test, e.g. top 3 collections
    n_for_top_collections: int

    # How many granules we will query
    granules_count: int

    # How many granules we will randomly select from the query
    granules_sample_size: int

    # The maximum allowed granule size; if larger we'll try to find another one
    granules_max_size_mb: int


daacs_list: list[TestParam] = [
    {
        "provider_name": "NSIDC_ECS",
        "n_for_top_collections": 3,
        "granules_count": 100,
        "granules_sample_size": 2,
        "granules_max_size_mb": 100,
    },
    # {
    #     "provider_name": "GES_DISC",
    #     "top_n_collections": 2,
    #     "granules_count": 100,
    #     "granules_sample_size": 2,
    #     "granules_max_size_mb": 130,
    # },
    # {
    #     "provider_name": "LPDAAC",
    #     "top_n_collections": 2,
    #     "granules_count": 100,
    #     "granules_sample_size": 2,
    #     "granules_max_size_mb": 100,
    # },
]


def top_collections_for_provider(provider: str, *, n: int) -> list[str]:
    """Return the top collections for this provider.

    Local cache is used as the source for this list. Run
    `./popular_collections/generate.py` to refresh it!

    TODO: Skip / exclude collections that have a EULA; filter them out in this function
    or use a pytest skip/xfail mark?
    """
    popular_collections_dir = Path(__file__).parent / "popular_collections"
    popular_collections_file = popular_collections_dir / f"{provider}.txt"
    with open(popular_collections_file) as f:
        popular_collections = f.read().splitlines()

    return popular_collections[:n]


def supported_collection(data_links):
    return all("podaac-tools.jpl.nasa.gov/drive" not in url for url in data_links)


@pytest.mark.parametrize("daac", daacs_list)
def test_earthaccess_can_download_onprem_collection_granules(tmp_path, daac):
    """Tests that we can download on-premises collections using HTTPS links."""
    provider = daac["provider_name"]
    n_for_top_collections = daac["n_for_top_collections"]

    granules_count = daac["granules_count"]
    granules_sample_size = daac["granules_sample_size"]
    granules_max_size = daac["granules_max_size_mb"]

    top_collections = top_collections_for_provider(
        provider,
        n=n_for_top_collections,
    )
    logger.info(f"On-premises collections for {provider}: {len(top_collections)}")

    for concept_id in top_collections:
        granule_query = DataGranules().concept_id(concept_id)
        total_granules = granule_query.hits()
        granules = granule_query.get(granules_count)
        assert len(granules) > 0, "Could not fetch granules"
        assert isinstance(granules[0], earthaccess.DataGranule)
        data_links = granules[0].data_links()
        if not supported_collection(data_links):
            logger.warning(f"PODAAC DRIVE is not supported at the moment: {data_links}")
            continue
        granules_to_download, total_size_cmr = get_sample_granules(
            granules,
            granules_sample_size,
            granules_max_size,
            round_ndigits=2,
        )
        if len(granules_to_download) == 0:
            logger.debug(
                f"Skipping {concept_id}, granule size exceeds configured max size"
            )
            continue
        logger.info(
            f"Testing {concept_id}, granules in collection: {total_granules}, "
            f"download size(MB): {total_size_cmr}"
        )
        path = tmp_path / "tests" / "integration" / "data" / concept_id
        path.mkdir(parents=True)
        store = Store(Auth().login(strategy="environment"))
        # We are testing this method
        downloaded_results = store.get(granules_to_download, local_path=path)

        assert isinstance(downloaded_results, list)
        assert len(downloaded_results) >= granules_sample_size

        # test that we downloaded the mb reported by CMR
        total_mb_downloaded = round(
            (sum(file.stat().st_size for file in path.rglob("*")) / 1024**2), 2
        )
        # clean the directory
        shutil.rmtree(path)

        # test that we could download the data
        if total_mb_downloaded <= 0:
            logger.warning(f"earthaccess could not download {concept_id}")
        if total_mb_downloaded != total_size_cmr:
            logger.warning(
                f"Warning: {concept_id} downloaded size {total_mb_downloaded}MB is "
                f"different from the size reported by CMR: {total_size_cmr}MB"
            )
