import psutil
from PIL import Image
from trame.decorators import TrameApp, change
from nrtk_explorer.app.images.image_ids import (
    dataset_id_to_image_id,
    dataset_id_to_transformed_image_id,
)
from nrtk_explorer.app.images.cache import LruCache


IMAGE_CACHE_SIZE_DEFAULT = 50
AVALIBLE_MEMORY_TO_TAKE_FACTOR = 0.4


@TrameApp()
class Images:
    def __init__(self, server):
        self.server = server
        self.original_images = LruCache(IMAGE_CACHE_SIZE_DEFAULT)
        self.transformed_images = LruCache(IMAGE_CACHE_SIZE_DEFAULT)
        self._should_ajust_cache_size = True
        self._transform = None

    def _ajust_cache_size(self, image_example: Image.Image):
        img_size = len(image_example.tobytes())
        system_memory = psutil.virtual_memory().available
        mem_for_cache = round(system_memory * AVALIBLE_MEMORY_TO_TAKE_FACTOR)
        images_that_fit = max(min(mem_for_cache // img_size, 500), 50)
        cache_size = images_that_fit // 2
        self.original_images = LruCache(cache_size)
        self.transformed_images = LruCache(cache_size)

    def _load_image(self, dataset_id: str):
        img = self.server.context.dataset.get_image(int(dataset_id))
        img.load()  # Avoid OSError(24, 'Too many open files')

        if self._should_ajust_cache_size:
            self._should_ajust_cache_size = False
            self._ajust_cache_size(img)  # assuming images in dataset are similar size

        # transforms and base64 encoding require RGB mode
        return img.convert("RGB") if img.mode != "RGB" else img

    def get_image(self, dataset_id: str, **kwargs):
        """For cache side effects pass on_add_item and on_clear_item callbacks as kwargs"""
        image_id = dataset_id_to_image_id(dataset_id)
        image = self.original_images.get_item(image_id) or self._load_image(dataset_id)
        self.original_images.add_item(image_id, image, **kwargs)
        return image

    def get_image_without_cache_eviction(self, dataset_id: str):
        """
        Does not remove items from cache, only adds.
        For computing metrics on all images.
        """
        image_id = dataset_id_to_image_id(dataset_id)
        image = self.original_images.get_item(image_id) or self._load_image(dataset_id)
        self.original_images.add_if_room(image_id, image)
        return image

    def _load_transformed_image(self, dataset_id: str):
        original = self.get_image_without_cache_eviction(dataset_id)
        transformed = self._transform.execute(original)
        # So pixel-wise annotation similarity score works
        if original.size != transformed.size:
            return transformed.resize(original.size)
        return transformed

    def _get_transformed_image(self, dataset_id: str, **kwargs):
        image_id = dataset_id_to_transformed_image_id(dataset_id)
        image = self.transformed_images.get_item(image_id) or self._load_transformed_image(
            dataset_id
        )
        return image_id, image

    def get_transformed_image(self, dataset_id: str, **kwargs):
        image_id, image = self._get_transformed_image(dataset_id, **kwargs)
        self.transformed_images.add_item(image_id, image, **kwargs)
        return image

    def get_transformed_image_without_cache_eviction(self, dataset_id: str):
        image_id, image = self._get_transformed_image(dataset_id)
        self.transformed_images.add_if_room(image_id, image)
        return image

    @change("current_dataset")
    def clear_all(self, **kwargs):
        self.original_images.clear()
        self.transformed_images.clear()
        self._should_ajust_cache_size = True

    def set_transform(self, transform):
        self._transform = transform
        self.transformed_images.clear()
