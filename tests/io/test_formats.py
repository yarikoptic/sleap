import os
from pathlib import Path, PurePath

import numpy as np
import pandas as pd
from numpy.testing import assert_array_equal
import pytest
import nixio

from sleap.io.video import Video
from sleap.instance import Instance, LabeledFrame, PredictedInstance, Track
from sleap.io.dataset import Labels
from sleap.io.format import read, dispatch, adaptor, text, genericjson, hdf5, filehandle
from sleap.io.format.adaptor import SleapObjectType
from sleap.io.format.alphatracker import AlphaTrackerAdaptor
from sleap.io.format.ndx_pose import NDXPoseAdaptor
from sleap.io.format.nix import NixAdaptor
from sleap.gui.commands import ImportAlphaTracker
from sleap.gui.app import MainWindow
from sleap.gui.state import GuiState
from sleap.info.write_tracking_h5 import get_nodes_as_np_strings


def test_text_adaptor(tmpdir):
    disp = dispatch.Dispatch()
    disp.register(text.TextAdaptor())

    filename = os.path.join(tmpdir, "textfile.txt")
    some_text = "some text to save in a file"

    disp.write(filename, some_text)

    read_text = disp.read(filename)

    assert some_text == read_text


def test_json_adaptor(tmpdir):
    disp = dispatch.Dispatch()
    disp.register(genericjson.GenericJsonAdaptor())

    filename = os.path.join(tmpdir, "jsonfile.json")
    d = dict(foo=123, bar="zip")

    disp.write(filename, d)

    read_dict = disp.read(filename)

    assert d == read_dict

    assert disp.open(filename).is_json


def test_invalid_json(tmpdir):
    # Write an "invalid" json file
    filename = os.path.join(tmpdir, "textfile.json")
    some_text = "some text to save in a file"
    with open(filename, "w") as f:
        f.write(some_text)

    disp = dispatch.Dispatch()
    disp.register(genericjson.GenericJsonAdaptor())

    assert not disp.open(filename).is_json

    with pytest.raises(TypeError):
        disp.read(filename)


def test_no_matching_adaptor():
    disp = dispatch.Dispatch()

    with pytest.raises(TypeError):
        disp.write("foo.txt", "foo")

    err = disp.write_safely("foo.txt", "foo")

    assert err is not None


def test_failed_read():
    disp = dispatch.Dispatch()
    disp.register(text.TextAdaptor())

    # Attempt to read hdf5 using text adaptor
    hdf5_filename = "tests/data/hdf5_format_v1/training.scale=0.50,sigma=10.h5"
    x, err = disp.read_safely(hdf5_filename)

    # There should be an error
    assert err is not None


def test_missing_file():
    disp = dispatch.Dispatch()
    disp.register(text.TextAdaptor())

    with pytest.raises(FileNotFoundError):
        disp.read("missing_file.txt")


def test_hdf5_v1(tmpdir, centered_pair_predictions_hdf5_path):
    filename = centered_pair_predictions_hdf5_path
    disp = dispatch.Dispatch.make_dispatcher(adaptor.SleapObjectType.labels)

    # Make sure reading works
    x = disp.read(filename)
    assert len(x.labeled_frames) == 1100

    # Make sure writing works
    filename = os.path.join(tmpdir, "test.h5")
    disp.write(filename, x)

    # Make sure we can read the file we just wrote
    y = disp.read(filename)
    assert len(y.labeled_frames) == 1100


def test_hdf5_v1_filehandle(centered_pair_predictions_hdf5_path):

    filename = centered_pair_predictions_hdf5_path

    labels = hdf5.LabelsV1Adaptor.read_headers(filehandle.FileHandle(filename))

    assert len(labels.videos) == 1
    assert (
        labels.videos[0].backend.filename
        == "tests/data/json_format_v1/centered_pair_low_quality.mp4"
    )


def test_csv(tmpdir, min_labels_slp, minimal_instance_predictions_csv_path):
    from sleap.info.write_tracking_h5 import main as write_analysis

    filename_csv = str(tmpdir + "\\analysis.csv")
    write_analysis(min_labels_slp, output_path=filename_csv, all_frames=True, csv=True)

    labels_csv = pd.read_csv(filename_csv)

    csv_predictions = pd.read_csv(minimal_instance_predictions_csv_path)

    assert labels_csv.equals(csv_predictions)

    labels = min_labels_slp

    # check number of cols
    assert len(labels_csv.columns) - 3 == len(get_nodes_as_np_strings(labels)) * 3


def test_analysis_hdf5(tmpdir, centered_pair_predictions):
    from sleap.info.write_tracking_h5 import main as write_analysis

    filename = os.path.join(tmpdir, "analysis.h5")
    video = centered_pair_predictions.videos[0]

    write_analysis(centered_pair_predictions, output_path=filename, all_frames=True)

    labels = read(
        filename,
        for_object="labels",
        as_format="analysis",
        video=video,
    )

    assert len(labels) == len(centered_pair_predictions)
    assert len(labels.tracks) == len(centered_pair_predictions.tracks)
    assert len(labels.all_instances) == len(centered_pair_predictions.all_instances)


def test_json_v1(tmpdir, centered_pair_labels):
    filename = os.path.join(tmpdir, "test.json")
    disp = dispatch.Dispatch.make_dispatcher(adaptor.SleapObjectType.labels)

    disp.write(filename, centered_pair_labels)

    # Make sure we can read the file we just wrote
    y = disp.read(filename)
    assert len(y.labeled_frames) == len(centered_pair_labels.labeled_frames)


def test_matching_adaptor(centered_pair_predictions_hdf5_path):
    from sleap.io.format import read

    read(
        centered_pair_predictions_hdf5_path,
        for_object="labels",
        as_format="*",
    )

    read(
        "tests/data/json_format_v1/centered_pair.json",
        for_object="labels",
        as_format="*",
    )


@pytest.mark.parametrize(
    "test_data",
    [
        "tests/data/dlc/labeled-data/video/madlc_testdata.csv",
        "tests/data/dlc/labeled-data/video/madlc_testdata_v2.csv",
    ],
)
def test_madlc(test_data):
    labels = read(
        test_data,
        for_object="labels",
        as_format="deeplabcut",
    )

    assert labels.skeleton.node_names == ["A", "B", "C"]
    assert len(labels.videos) == 1
    assert len(labels.video.filenames) == 4
    assert labels.videos[0].filenames[0].endswith("img000.png")
    assert labels.videos[0].filenames[1].endswith("img001.png")
    assert labels.videos[0].filenames[2].endswith("img002.png")
    assert labels.videos[0].filenames[3].endswith("img003.png")

    # Assert frames without any coor are not labeled
    assert len(labels) == 3

    # Assert number of instances per frame is correct
    assert len(labels[0]) == 2
    assert len(labels[1]) == 2
    assert len(labels[2]) == 1

    assert_array_equal(labels[0][0].numpy(), [[0, 1], [2, 3], [4, 5]])
    assert_array_equal(labels[0][1].numpy(), [[6, 7], [8, 9], [10, 11]])
    assert_array_equal(labels[1][0].numpy(), [[12, 13], [np.nan, np.nan], [15, 16]])
    assert_array_equal(labels[1][1].numpy(), [[17, 18], [np.nan, np.nan], [20, 21]])
    assert_array_equal(labels[2][0].numpy(), [[22, 23], [24, 25], [26, 27]])
    assert labels[2].frame_idx == 3


@pytest.mark.parametrize(
    "test_data",
    [
        "tests/data/dlc/labeled-data/video/maudlc_testdata.csv",
        "tests/data/dlc/labeled-data/video/maudlc_testdata_v2.csv",
        "tests/data/dlc/madlc_230_config.yaml",
    ],
)
def test_maudlc(test_data):
    labels = read(
        test_data,
        for_object="labels",
        as_format="deeplabcut",
    )

    assert labels.skeleton.node_names == ["A", "B", "C", "D", "E"]
    assert len(labels.videos) == 1
    assert len(labels.video.filenames) == 4
    assert labels.videos[0].filenames[0].endswith("img000.png")
    assert labels.videos[0].filenames[1].endswith("img001.png")
    assert labels.videos[0].filenames[2].endswith("img002.png")
    assert labels.videos[0].filenames[3].endswith("img003.png")

    # Assert frames without any coor are not labeled
    assert len(labels) == 3

    # Assert number of instances per frame is correct
    assert len(labels[0]) == 2
    assert len(labels[1]) == 3
    assert len(labels[2]) == 2

    assert_array_equal(
        labels[0][0].numpy(),
        [[0, 1], [2, 3], [4, 5], [np.nan, np.nan], [np.nan, np.nan]],
    )
    assert_array_equal(
        labels[0][1].numpy(),
        [[6, 7], [8, 9], [10, 11], [np.nan, np.nan], [np.nan, np.nan]],
    )
    assert_array_equal(
        labels[1][0].numpy(),
        [[12, 13], [np.nan, np.nan], [15, 16], [np.nan, np.nan], [np.nan, np.nan]],
    )
    assert_array_equal(
        labels[1][1].numpy(),
        [[17, 18], [np.nan, np.nan], [20, 21], [np.nan, np.nan], [np.nan, np.nan]],
    )
    assert_array_equal(
        labels[1][2].numpy(),
        [[np.nan, np.nan], [np.nan, np.nan], [np.nan, np.nan], [22, 23], [24, 25]],
    )
    assert_array_equal(
        labels[2][0].numpy(),
        [[26, 27], [28, 29], [30, 31], [np.nan, np.nan], [np.nan, np.nan]],
    )
    assert_array_equal(
        labels[2][1].numpy(),
        [[np.nan, np.nan], [np.nan, np.nan], [np.nan, np.nan], [32, 33], [34, 35]],
    )
    assert labels[2].frame_idx == 3

    # Assert tracks are correct
    assert len(labels.tracks) == 3
    sorted_animals = sorted(["Animal1", "Animal2", "single"])
    assert sorted([t.name for t in labels.tracks]) == sorted_animals
    for t in labels.tracks:
        if t.name == "single":
            assert t.spawned_on == 1
        else:
            assert t.spawned_on == 0


@pytest.mark.parametrize(
    "test_data",
    [
        "tests/data/dlc/labeled-data/video/dlc_testdata.csv",
        "tests/data/dlc/labeled-data/video/dlc_testdata_v2.csv",
    ],
)
def test_sadlc(test_data):
    labels = read(
        test_data,
        for_object="labels",
        as_format="deeplabcut",
    )

    assert labels.skeleton.node_names == ["A", "B", "C"]
    assert len(labels.videos) == 1
    assert len(labels.video.filenames) == 4
    assert labels.videos[0].filenames[0].endswith("img000.png")
    assert labels.videos[0].filenames[1].endswith("img001.png")
    assert labels.videos[0].filenames[2].endswith("img002.png")
    assert labels.videos[0].filenames[3].endswith("img003.png")

    # Assert frames without any coor are not labeled
    assert len(labels) == 3

    # Assert number of instances per frame is correct
    assert len(labels[0]) == 1
    assert len(labels[1]) == 1
    assert len(labels[2]) == 1

    assert_array_equal(labels[0][0].numpy(), [[0, 1], [2, 3], [4, 5]])
    assert_array_equal(labels[1][0].numpy(), [[12, 13], [np.nan, np.nan], [15, 16]])
    assert_array_equal(labels[2][0].numpy(), [[22, 23], [24, 25], [26, 27]])
    assert labels[2].frame_idx == 3


def test_alphatracker(qtbot):

    # Checks on properties
    at_adaptor = AlphaTrackerAdaptor()
    assert at_adaptor.handles == SleapObjectType.labels
    assert at_adaptor.default_ext == "json"
    assert at_adaptor.name == "AlphaTracker Dataset JSON"
    assert at_adaptor.can_write_filename("cannot_write_this.txt") == False
    assert at_adaptor.does_read() == True
    assert at_adaptor.does_write() == False
    with pytest.raises(NotImplementedError):
        at_adaptor.write("file_that_will_not_be_written", Labels())
    assert at_adaptor.formatted_ext_options == f"AlphaTracker Dataset JSON (json)"

    # Begin checks on functionality

    filename = "tests/data/alphatracker/at_testdata.json"
    disp = dispatch.Dispatch()
    disp.register(AlphaTrackerAdaptor)

    # Ensure reading works
    labels: Labels = disp.read(filename)
    lfs = labels.labeled_frames

    # Ensure video and frames are read correctly
    assert len(lfs) == 4
    for file_idx, file in enumerate(labels.video.backend.filenames):
        f = Path(file)
        assert f.stem == f"img00{file_idx}"

    # Ensure nodes are read correctly
    nodes = labels.skeleton.node_names
    assert nodes[0] == "1"
    assert nodes[1] == "2"
    assert nodes[2] == "3"

    # Ensure points are read correctly
    for lf_idx, lf in enumerate(lfs):
        assert len(lf.instances) == 2
        for inst_idx, inst in enumerate(lf.instances):
            for point_idx, point in enumerate(inst.points):
                assert point[0] == ((lf_idx + 1) * (inst_idx + 1))
                assert point[1] == (point_idx + 2)

    # Run through GUI display

    app = MainWindow(no_usage_data=True)
    app.state = GuiState()
    app.state["filename"] = filename

    # Only test do_action because ask method opens FileDialog
    ImportAlphaTracker().do_action(context=app.commands, params=app.state)


def test_tracking_scores(tmpdir, centered_pair_predictions_slp_path):

    # test reading
    filename = centered_pair_predictions_slp_path

    fh = filehandle.FileHandle(filename)

    assert fh.format_id is not None

    labels = hdf5.LabelsV1Adaptor.read(fh)

    for instance in labels.instances():
        assert hasattr(instance, "tracking_score")

    # test writing
    filename = os.path.join(tmpdir, "test.slp")
    labels.save(filename)

    labels = hdf5.LabelsV1Adaptor.read(filehandle.FileHandle(filename))

    for instance in labels.instances():
        assert hasattr(instance, "tracking_score")


def assert_read_labels_match(labels, read_labels):
    # Labeled Frames
    assert len(read_labels.labeled_frames) == len(labels.labeled_frames)

    # Instances
    frame_idx = 7
    read_instances = read_labels[frame_idx].instances
    instances = labels[frame_idx]
    assert len(instances) == len(read_instances)

    # Points
    for read_inst, inst in zip(read_instances, instances):
        for read_points, points in zip(read_inst.points, inst.points):
            assert read_points == points

    # Video
    assert len(read_labels.videos) == len(labels.videos)
    for video_idx, _ in enumerate(labels.videos):
        # The ordering of reading processing modules from NWB files seems to vary
        try:
            assert PurePath(read_labels.videos[video_idx].backend.filename) == PurePath(
                labels.videos[video_idx].backend.filename
            )
            assert isinstance(
                read_labels.videos[video_idx].backend,
                type(labels.videos[video_idx].backend),
            )
        except:
            assert PurePath(read_labels.videos[video_idx].backend.filename) == PurePath(
                labels.videos[video_idx - 1].backend.filename
            )
            assert isinstance(
                read_labels.videos[video_idx].backend,
                type(labels.videos[video_idx - 1].backend),
            )

    # Skeleton
    assert read_labels.skeleton.node_names == labels.skeleton.node_names
    assert read_labels.skeleton.edge_inds == labels.skeleton.edge_inds
    assert len(read_labels.tracks) == len(labels.tracks)


def test_nwb(
    centered_pair_predictions: Labels,
    small_robot_mp4_vid: Video,
    tmpdir,
):
    """Test that `Labels` can be written to and recreated from an NWB file."""

    labels = centered_pair_predictions
    filename = str(PurePath(tmpdir, "ndx_pose_test.nwb"))

    # Add another video with an untracked PredictedInstance
    labels.videos.append(small_robot_mp4_vid)
    pred_instance: PredictedInstance = PredictedInstance.from_instance(
        labels[0].instances[0], score=5
    )
    pred_instance.track = None
    lf = LabeledFrame(video=small_robot_mp4_vid, frame_idx=6, instances=[pred_instance])
    labels.append(lf)

    # Write to NWB file
    NDXPoseAdaptor.write(NDXPoseAdaptor, filename, labels)

    # Read from NWB file
    read_labels = NDXPoseAdaptor.read(NDXPoseAdaptor, filehandle.FileHandle(filename))
    assert_read_labels_match(labels, read_labels)

    # Append to NWB File (no changes expected)
    NDXPoseAdaptor.write(NDXPoseAdaptor, filename, labels)
    read_labels = NDXPoseAdaptor.read(NDXPoseAdaptor, filehandle.FileHandle(filename))
    assert_read_labels_match(labels, read_labels)

    # Project with no predicted instances
    labels.instances = []
    with pytest.raises(TypeError):
        NDXPoseAdaptor.write(NDXPoseAdaptor, filename, labels)


def test_nix_adaptor(
    centered_pair_predictions: Labels,
    small_robot_mp4_vid: Video,
    tmpdir,
):
    # general tests
    na = NixAdaptor()
    assert na.default_ext == "nix"
    assert "nix" in na.all_exts
    assert len(na.name) > 0
    assert na.can_write_filename("somefile.nix")
    assert not na.can_write_filename("somefile.slp")
    assert NixAdaptor.does_read() == False
    assert NixAdaptor.does_write() == True

    with pytest.raises(NotImplementedError):
        NixAdaptor.read("some file")

    print("writing test predictions to nix file...")
    filename = str(PurePath(tmpdir, "ndx_pose_test.nix"))
    with pytest.raises(ValueError):
        NixAdaptor.write(filename, centered_pair_predictions, video=small_robot_mp4_vid)
    NixAdaptor.write(filename, centered_pair_predictions)
    NixAdaptor.write(
        filename, centered_pair_predictions, video=centered_pair_predictions.videos[0]
    )

    # basic read tests using the generic nix library
    import nixio

    file = nixio.File.open(filename, nixio.FileMode.ReadOnly)
    try:
        file_meta = file.sections[0]
        assert file_meta["format"] == "nix.tracking"
        assert "sleap" in file_meta["writer"].lower()

        assert len([b for b in file.blocks if b.type == "nix.tracking_results"]) > 0
        b = file.blocks[0]
        assert (
            len(
                [
                    da
                    for da in b.data_arrays
                    if da.type == "nix.tracking.instance_position"
                ]
            )
            == 1
        )
        assert (
            len(
                [
                    da
                    for da in b.data_arrays
                    if da.type == "nix.tracking.instance_frameidx"
                ]
            )
            == 1
        )

        inst_positions = b.data_arrays["position"]
        assert len(inst_positions.shape) == 3
        assert len(inst_positions.shape) == len(inst_positions.dimensions)
        assert inst_positions.shape[2] == len(centered_pair_predictions.nodes)

        frame_indices = b.data_arrays["frame"]
        assert len(frame_indices.shape) == 1
        assert frame_indices.shape[0] == inst_positions.shape[0]
    except Exception as e:
        file.close()
        raise e


def read_nix_meta(filename, *args, **kwargs):
    file = nixio.File.open(filename, nixio.FileMode.ReadOnly)
    try:
        file_meta = file_meta = file.sections[0]
    except Exception:
        file.close()

    return file_meta
