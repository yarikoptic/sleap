"""Utilities for generating data for track identity models."""

import sleap
import tensorflow as tf
import attr
from typing import List, Text


def make_class_vectors(class_inds: tf.Tensor, n_classes: int) -> tf.Tensor:
    """Make a binary class vectors from class indices.

    Args:
        class_inds: Class indices as `tf.Tensor` of dtype `tf.int32` and shape
            `(n_instances,)`. Indices of `-1` will be interpreted as having no class.
        n_classes: Integer number of maximum classes.

    Returns:
        A tensor with binary class vectors of shape `(n_instances, n_classes)` of dtype
        `tf.int32`. Instances with no class will have all zeros in their row.

    Notes: A class index can be used to represent a track index.
    """
    return tf.one_hot(class_inds, n_classes, dtype=tf.int32)


def make_class_maps(
    confmaps: tf.Tensor, class_inds: tf.Tensor, n_classes: int, threshold: float = 0.2
) -> tf.Tensor:
    """Generate identity class maps using instance-wise confidence maps.

    This is useful for making class maps defined on local neighborhoods around the
    peaks.

    Args:
        confmaps: Confidence maps for the same points as the offset maps as a
            `tf.Tensor` of shape `(grid_height, grid_width, n_instances)` and dtype
            `tf.float32`. This can be generated by
            `sleap.nn.data.confidence_maps.make_confmaps`.
        class_inds: Class indices as `tf.int32` tensor of shape `(n_instances)`.
        n_classes: Integer number of maximum classes.
        threshold: Minimum confidence map value below which map values will be replaced
            with zeros.

    Returns:
        The class maps with shape `(grid_height, grid_width, n_classes)` and dtype
        `tf.float32` where each channel will be a binary mask with 1 where the instance
        confidence maps were higher than the threshold.

    Notes:
        Pixels that have confidence map values from more than one animal will have the
        class vectors weighed by the relative contribution of each instance.

    See also: make_class_vectors, sleap.nn.data.confidence_maps.make_confmaps
    """
    n_classes = tf.squeeze(n_classes)
    n_instances = tf.shape(confmaps)[2]
    class_vectors = make_class_vectors(class_inds, n_classes)
    class_vectors = tf.reshape(
        tf.cast(class_vectors, tf.float32),
        [1, 1, n_instances, n_classes],
    )

    # Normalize instance mask.
    mask = confmaps / tf.reduce_sum(confmaps, axis=2, keepdims=True)
    mask = tf.where(confmaps > threshold, mask, 0.0)  # (h, w, n_instances)
    mask = tf.expand_dims(mask, axis=3)  # (h, w, n_instances, 1)

    # Apply mask to vectors to create class maps.
    class_maps = tf.reduce_max(mask * class_vectors, axis=2)
    return class_maps


@attr.s(auto_attribs=True)
class ClassVectorGenerator:
    """Transformer to generate class probability vectors from track indices."""

    @property
    def input_keys(self) -> List[Text]:
        """Return the keys that incoming elements are expected to have."""
        return ["track_inds", "n_tracks"]

    @property
    def output_keys(self) -> List[Text]:
        """Return the keys that outgoing elements will have."""
        return self.input_keys + ["class"]

    def transform_dataset(self, input_ds: tf.data.Dataset) -> tf.data.Dataset:
        """Create a dataset that contains the generated class identity vectors.

        Args:
            input_ds: A dataset with elements that contain the keys`"track_inds"` and
                `"n_tracks"`.

        Returns:
            A `tf.data.Dataset` with the same keys as the input, as well as a `"class"`
            key containing the generated class vectors.
        """

        def generate_class_vectors(example):
            """Local processing function for dataset mapping."""
            example["class"] = tf.cast(
                make_class_vectors(example["track_inds"], example["n_tracks"]),
                tf.float32,
            )
            return example

        # Map transformation.
        output_ds = input_ds.map(
            generate_class_vectors, num_parallel_calls=tf.data.experimental.AUTOTUNE
        )
        return output_ds


@attr.s(auto_attribs=True)
class ClassMapGenerator:
    """Transformer to generate class maps from track indices.

    Attributes:
        sigma: Standard deviation of the 2D Gaussian distribution sampled to generate
            confidence maps for masking the identity maps. This defines the spread in
            units of the input image's grid, i.e., it does not take scaling in previous
            steps into account.
        output_stride: Relative stride of the generated maps. This is effectively the
            reciprocal of the output scale, i.e., increase this to generate maps that
            are smaller than the input images.
        centroids: If `True`, generate masking confidence maps for centroids rather than
            instance points.
        class_map_threshold: Minimum confidence map value below which map values will be
            replaced with zeros.
    """

    sigma: float = 2.0
    output_stride: int = 1
    centroids: bool = False
    class_map_threshold: float = 0.2

    @property
    def input_keys(self) -> List[Text]:
        """Return the keys that incoming elements are expected to have."""
        if self.centroids:
            return ["centroids", "track_inds", "n_tracks"]
        else:
            return ["instances", "track_inds", "n_tracks"]

    @property
    def output_keys(self) -> List[Text]:
        """Return the keys that outgoing elements will have."""
        return self.input_keys + ["class_maps"]

    def transform_dataset(self, input_ds: tf.data.Dataset) -> tf.data.Dataset:
        """Create a dataset that contains the generated class identity maps.

        Args:
            input_ds: A dataset with elements that contain the keys `"image"`,
                `"track_inds"`, `"n_tracks"` and either `"instances"` or `"centroids"`
                depending on whether the `centroids` attribute is set to `True`.

        Returns:
            A `tf.data.Dataset` with the same keys as the input, as well as a
            `"class_maps"` key containing the generated class maps.
        """
        # Infer image dimensions to generate the full scale sampling grid.
        test_example = next(iter(input_ds))
        image_height = test_example["image"].shape[0]
        image_width = test_example["image"].shape[1]

        # Generate sampling grid vectors.
        xv, yv = sleap.nn.data.confidence_maps.make_grid_vectors(
            image_height=image_height,
            image_width=image_width,
            output_stride=self.output_stride,
        )

        def generate_class_maps(example):
            """Local processing function for dataset mapping."""
            if self.centroids:
                points = tf.expand_dims(
                    example["centroids"], axis=0
                )  # (1, n_instances, 2)
            else:
                points = tf.transpose(
                    example["instances"], [1, 0, 2]
                )  # (n_nodes, n_instances, 2)

            # Generate confidene maps for masking.
            cms = sleap.nn.data.confidence_maps.make_multi_confmaps(
                points, xv, yv, self.sigma * self.output_stride
            )  # (height, width, n_instances)

            example["class_maps"] = make_class_maps(
                cms,
                class_inds=example["track_inds"],
                n_classes=example["n_tracks"],
                threshold=self.class_map_threshold,
            )
            return example

        # Map transformation.
        output_ds = input_ds.map(
            generate_class_maps, num_parallel_calls=tf.data.experimental.AUTOTUNE
        )
        return output_ds
