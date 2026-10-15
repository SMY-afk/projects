import pytest

from backend.app.services.sample_owned_page_url import build_owned_sample_url
from backend.app.services.sample_persistent_target import persistent_sample_key

HOST = 'affiliate.tiktokshopglobalselling.com'
PATH = '/affiliate/sample/sample-request'


def target(shop='123', host=HOST):
    return [{'id': 'approved-page', 'type': 'page',
             'url': f'https://{host}/affiliate/creator?shop_id={shop}&shop_region=US'}]


def test_approved_page_navigated_to_creator_can_return_to_samples():
    assert build_owned_sample_url(target(), '123', host=HOST, path=PATH,
                                  approved_target_id='approved-page') == (
        f'https://{HOST}{PATH}?shop_region=US&shop_id=123'
    )


@pytest.mark.parametrize('pages, approved', [
    (target(), None), (target('456'), 'approved-page'),
    (target(host='example.com'), 'approved-page'), (target(), 'other-page'),
])
def test_recovery_never_guesses_unapproved_or_other_shop(pages, approved):
    assert build_owned_sample_url(pages, '123', host=HOST, path=PATH,
                                  approved_target_id=approved) is None


@pytest.mark.parametrize('shop', ['9622543325839925006', '9472478445887813622'])
def test_cross3_and_cross12_share_reusable_page_for_free_and_paid(shop):
    assert persistent_sample_key(shop, 'free') == (shop, 'free')
    assert persistent_sample_key(shop, 'refundable') == (shop, 'free')
