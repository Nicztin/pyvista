"""Module containing pyvista implementation of vtkRenderer."""

import collections
import logging
from weakref import proxy

import numpy as np
import vtk
from vtk import vtkRenderer

import pyvista
from pyvista.utilities import wrap

from .theme import parse_color, parse_font_family, rcParams, MAX_N_COLOR_BARS
from .tools import create_axes_marker



def scale_point(camera, point, invert=False):
    """Scale a point using the camera's transform matrix.

    Parameters
    ----------
    camera : vtk.vtkCamera
        The camera who's matrix to use.

    point : tuple(float)
        Length 3 tuple of the point coordinates.

    invert : bool
        If True, invert the matrix to transform the point out of the
        camera's transformed space. Default is False to transform a
        point from world coordinates to the camera's transformed space.

    """
    if invert:
        mtx = vtk.vtkMatrix4x4()
        mtx.DeepCopy(camera.GetModelTransformMatrix())
        mtx.Invert()
    else:
        mtx = camera.GetModelTransformMatrix()
    scaled = mtx.MultiplyDoublePoint((point[0], point[1], point[2], 0.0))
    return (scaled[0], scaled[1], scaled[2])


class Renderer(vtkRenderer):
    """Renderer class."""

    def __init__(self, parent, border=True, border_color=(1, 1, 1),
                 border_width=2.0):
        """Initialize the renderer."""
        super(Renderer, self).__init__()
        self._actors = {}
        self.parent = parent
        self.camera_set = False
        self.bounding_box_actor = None
        self.scale = [1.0, 1.0, 1.0]
        self.AutomaticLightCreationOff()

        # This is a private variable to keep track of how many colorbars exist
        # This allows us to keep adding colorbars without overlapping
        self._scalar_bar_slots = set(range(MAX_N_COLOR_BARS))
        self._scalar_bar_slot_lookup = {}

        if border:
            self.add_border(border_color, border_width)

    def enable_depth_peeling(self, number_of_peels=5, occlusion_ratio=0.1):
        """Enable depth peeling."""
        self.SetUseDepthPeeling(True)
        self.SetMaximumNumberOfPeels(number_of_peels)
        self.SetOcclusionRatio(occlusion_ratio)

    def disable_depth_peeling(self):
        """Disable depth peeling."""
        self.SetUseDepthPeeling(False)

    def enable_anti_aliasing(self):
        """Enable anti-aliasing FXAA."""
        self.SetUseFXAA(True)

    def disable_anti_aliasing(self):
        """Disable anti-aliasing FXAA."""
        self.SetUseFXAA(False)


    def add_border(self, color=[1, 1, 1], width=2.0):
        """Add borders around the frame."""
        points = np.array([[1., 1., 0.],
                           [0., 1., 0.],
                           [0., 0., 0.],
                           [1., 0., 0.]])

        lines = np.array([[2, 0, 1],
                          [2, 1, 2],
                          [2, 2, 3],
                          [2, 3, 0]]).ravel()

        poly = pyvista.PolyData()
        poly.points = points
        poly.lines = lines

        coordinate = vtk.vtkCoordinate()
        coordinate.SetCoordinateSystemToNormalizedViewport()

        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        mapper.SetTransformCoordinate(coordinate)

        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(parse_color(color))
        actor.GetProperty().SetLineWidth(width)

        self.AddViewProp(actor)


    def add_actor(self, uinput, reset_camera=False, name=None, loc=None,
                  culling=False, pickable=True):
        """Add an actor to render window.

        Creates an actor if input is a mapper.

        Parameters
        ----------
        uinput : vtk.vtkMapper or vtk.vtkActor
            vtk mapper or vtk actor to be added.

        reset_camera : bool, optional
            Resets the camera when true.

        loc : int, tuple, or list
            Index of the renderer to add the actor to.  For example,
            ``loc=2`` or ``loc=(1, 1)``.

        culling : str, optional
            Does not render faces that are culled. Options are ``'front'`` or
            ``'back'``. This can be helpful for dense surface meshes,
            especially when edges are visible, but can cause flat
            meshes to be partially displayed.  Default False.

        Return
        ------
        actor : vtk.vtkActor
            The actor.

        actor_properties : vtk.Properties
            Actor properties.

        """
        # Remove actor by that name if present
        rv = self.remove_actor(name, reset_camera=False)

        if isinstance(uinput, vtk.vtkMapper):
            actor = vtk.vtkActor()
            actor.SetMapper(uinput)
        else:
            actor = uinput

        self.AddActor(actor)
        actor.renderer = proxy(self)

        if name is None:
            name = str(hex(id(actor)))

        self._actors[name] = actor

        if reset_camera:
            self.reset_camera()
        elif not self.camera_set and reset_camera is None and not rv:
            self.reset_camera()
        else:
            self.parent._render()

        self.update_bounds_axes()

        if isinstance(culling, str):
            culling = culling.lower()

        if culling:
            if culling in [True, 'back', 'backface', 'b']:
                try:
                    actor.GetProperty().BackfaceCullingOn()
                except AttributeError:  # pragma: no cover
                    pass
            elif culling in ['front', 'frontface', 'f']:
                try:
                    actor.GetProperty().FrontfaceCullingOn()
                except AttributeError:  # pragma: no cover
                    pass
            else:
                raise RuntimeError('Culling option ({}) not understood.'.format(culling))

        actor.SetPickable(pickable)

        self.ResetCameraClippingRange()

        return actor, actor.GetProperty()


    def add_axes_at_origin(self, x_color=None, y_color=None, z_color=None,
                           xlabel='X', ylabel='Y', zlabel='Z', line_width=2,
                           labels_off=False):
        """Add axes actor at origin.

        Return
        ------
        marker_actor : vtk.vtkAxesActor
            vtkAxesActor actor

        """
        self.marker_actor = create_axes_marker(line_width=line_width,
            x_color=x_color, y_color=y_color, z_color=z_color,
            xlabel=xlabel, ylabel=ylabel, zlabel=zlabel, labels_off=labels_off)
        self.AddActor(self.marker_actor)
        self._actors[str(hex(id(self.marker_actor)))] = self.marker_actor
        return self.marker_actor

    def show_bounds(self, mesh=None, bounds=None, show_xaxis=True,
                    show_yaxis=True, show_zaxis=True, show_xlabels=True,
                    show_ylabels=True, show_zlabels=True, italic=False,
                    bold=True, shadow=False, font_size=None,
                    font_family=None, color=None,
                    xlabel='X Axis', ylabel='Y Axis', zlabel='Z Axis',
                    use_2d=False, grid=None, location='closest', ticks=None,
                    all_edges=False, corner_factor=0.5, loc=None, fmt=None,
                    minor_ticks=False, padding=0.0):
        """Add bounds axes.

        Shows the bounds of the most recent input mesh unless mesh is specified.

        Parameters
        ----------
        mesh : vtkPolydata or unstructured grid, optional
            Input mesh to draw bounds axes around

        bounds : list or tuple, optional
            Bounds to override mesh bounds.
            [xmin, xmax, ymin, ymax, zmin, zmax]

        show_xaxis : bool, optional
            Makes x axis visible.  Default True.

        show_yaxis : bool, optional
            Makes y axis visible.  Default True.

        show_zaxis : bool, optional
            Makes z axis visible.  Default True.

        show_xlabels : bool, optional
            Shows x labels.  Default True.

        show_ylabels : bool, optional
            Shows y labels.  Default True.

        show_zlabels : bool, optional
            Shows z labels.  Default True.

        italic : bool, optional
            Italicises axis labels and numbers.  Default False.

        bold : bool, optional
            Bolds axis labels and numbers.  Default True.

        shadow : bool, optional
            Adds a black shadow to the text.  Default False.

        font_size : float, optional
            Sets the size of the label font.  Defaults to 16.

        font_family : string, optional
            Font family.  Must be either courier, times, or arial.

        color : string or 3 item list, optional
            Color of all labels and axis titles.  Default white.
            Either a string, rgb list, or hex color string.  For example:

                color='white'
                color='w'
                color=[1, 1, 1]
                color='#FFFFFF'

        xlabel : string, optional
            Title of the x axis.  Default "X Axis"

        ylabel : string, optional
            Title of the y axis.  Default "Y Axis"

        zlabel : string, optional
            Title of the z axis.  Default "Z Axis"

        use_2d : bool, optional
            A bug with vtk 6.3 in Windows seems to cause this function
            to crash this can be enabled for smoother plotting for
            other environments.

        grid : bool or str, optional
            Add grid lines to the backface (``True``, ``'back'``, or
            ``'backface'``) or to the frontface (``'front'``,
            ``'frontface'``) of the axes actor.

        location : str, optional
            Set how the axes are drawn: either static (``'all'``),
            closest triad (``front``), furthest triad (``'back'``),
            static closest to the origin (``'origin'``), or outer
            edges (``'outer'``) in relation to the camera
            position. Options include: ``'all', 'front', 'back',
            'origin', 'outer'``

        ticks : str, optional
            Set how the ticks are drawn on the axes grid. Options include:
            ``'inside', 'outside', 'both'``

        all_edges : bool, optional
            Adds an unlabeled and unticked box at the boundaries of
            plot. Useful for when wanting to plot outer grids while
            still retaining all edges of the boundary.

        corner_factor : float, optional
            If ``all_edges````, this is the factor along each axis to
            draw the default box. Dafuault is 0.5 to show the full box.

        loc : int, tuple, or list
            Index of the renderer to add the actor to.  For example,
            ``loc=2`` or ``loc=(1, 1)``.  If None, selects the last
            active Renderer.

        padding : float, optional
            An optional percent padding along each axial direction to cushion
            the datasets in the scene from the axes annotations. Defaults to
            have no padding

        Return
        ------
        cube_axes_actor : vtk.vtkCubeAxesActor
            Bounds actor

        Examples
        --------
        >>> import pyvista
        >>> from pyvista import examples
        >>> mesh = pyvista.Sphere()
        >>> plotter = pyvista.Plotter()
        >>> _ = plotter.add_mesh(mesh)
        >>> _ = plotter.show_bounds(grid='front', location='outer', all_edges=True)
        >>> plotter.show() # doctest:+SKIP

        """
        self.remove_bounds_axes()

        if font_family is None:
            font_family = rcParams['font']['family']
        if font_size is None:
            font_size = rcParams['font']['size']
        if color is None:
            color = rcParams['font']['color']
        if fmt is None:
            fmt = rcParams['font']['fmt']

        color = parse_color(color)

        # Use the bounds of all data in the rendering window
        if mesh is None and bounds is None:
            bounds = self.bounds

        # create actor
        cube_axes_actor = vtk.vtkCubeAxesActor()
        if use_2d or not np.allclose(self.scale, [1.0, 1.0, 1.0]):
            cube_axes_actor.SetUse2DMode(True)
        else:
            cube_axes_actor.SetUse2DMode(False)

        if grid:
            if isinstance(grid, str) and grid.lower() in ('front', 'frontface'):
                cube_axes_actor.SetGridLineLocation(cube_axes_actor.VTK_GRID_LINES_CLOSEST)
            if isinstance(grid, str) and grid.lower() in ('both', 'all'):
                cube_axes_actor.SetGridLineLocation(cube_axes_actor.VTK_GRID_LINES_ALL)
            else:
                cube_axes_actor.SetGridLineLocation(cube_axes_actor.VTK_GRID_LINES_FURTHEST)
            # Only show user desired grid lines
            cube_axes_actor.SetDrawXGridlines(show_xaxis)
            cube_axes_actor.SetDrawYGridlines(show_yaxis)
            cube_axes_actor.SetDrawZGridlines(show_zaxis)
            # Set the colors
            cube_axes_actor.GetXAxesGridlinesProperty().SetColor(color)
            cube_axes_actor.GetYAxesGridlinesProperty().SetColor(color)
            cube_axes_actor.GetZAxesGridlinesProperty().SetColor(color)

        if isinstance(ticks, str):
            ticks = ticks.lower()
            if ticks in ('inside'):
                cube_axes_actor.SetTickLocationToInside()
            elif ticks in ('outside'):
                cube_axes_actor.SetTickLocationToOutside()
            elif ticks in ('both'):
                cube_axes_actor.SetTickLocationToBoth()
            else:
                raise ValueError('Value of ticks ({}) not understood.'.format(ticks))

        if isinstance(location, str):
            location = location.lower()
            if location in ('all'):
                cube_axes_actor.SetFlyModeToStaticEdges()
            elif location in ('origin'):
                cube_axes_actor.SetFlyModeToStaticTriad()
            elif location in ('outer'):
                cube_axes_actor.SetFlyModeToOuterEdges()
            elif location in ('default', 'closest', 'front'):
                cube_axes_actor.SetFlyModeToClosestTriad()
            elif location in ('furthest', 'back'):
                cube_axes_actor.SetFlyModeToFurthestTriad()
            else:
                raise ValueError('Value of location ({}) not understood.'.format(location))

        # set bounds
        if bounds is None:
            bounds = np.array(mesh.GetBounds())
        if isinstance(padding, (int, float)) and 0.0 <= padding < 1.0:
            if not np.any(np.abs(bounds) == np.inf):
                cushion = np.array([np.abs(bounds[1] - bounds[0]),
                                    np.abs(bounds[3] - bounds[2]),
                                    np.abs(bounds[5] - bounds[4])]) * padding
                bounds[::2] -= cushion
                bounds[1::2] += cushion
        else:
            raise ValueError('padding ({}) not understood. Must be float between 0 and 1'.format(padding))
        cube_axes_actor.SetBounds(bounds)

        # show or hide axes
        cube_axes_actor.SetXAxisVisibility(show_xaxis)
        cube_axes_actor.SetYAxisVisibility(show_yaxis)
        cube_axes_actor.SetZAxisVisibility(show_zaxis)

        # disable minor ticks
        if not minor_ticks:
            cube_axes_actor.XAxisMinorTickVisibilityOff()
            cube_axes_actor.YAxisMinorTickVisibilityOff()
            cube_axes_actor.ZAxisMinorTickVisibilityOff()

        cube_axes_actor.SetCamera(self.camera)

        # set color
        cube_axes_actor.GetXAxesLinesProperty().SetColor(color)
        cube_axes_actor.GetYAxesLinesProperty().SetColor(color)
        cube_axes_actor.GetZAxesLinesProperty().SetColor(color)

        # empty arr
        empty_str = vtk.vtkStringArray()
        empty_str.InsertNextValue('')

        # show lines
        if show_xaxis:
            cube_axes_actor.SetXTitle(xlabel)
        else:
            cube_axes_actor.SetXTitle('')
            cube_axes_actor.SetAxisLabels(0, empty_str)

        if show_yaxis:
            cube_axes_actor.SetYTitle(ylabel)
        else:
            cube_axes_actor.SetYTitle('')
            cube_axes_actor.SetAxisLabels(1, empty_str)

        if show_zaxis:
            cube_axes_actor.SetZTitle(zlabel)
        else:
            cube_axes_actor.SetZTitle('')
            cube_axes_actor.SetAxisLabels(2, empty_str)

        # show labels
        if not show_xlabels:
            cube_axes_actor.SetAxisLabels(0, empty_str)

        if not show_ylabels:
            cube_axes_actor.SetAxisLabels(1, empty_str)

        if not show_zlabels:
            cube_axes_actor.SetAxisLabels(2, empty_str)

        # set font
        font_family = parse_font_family(font_family)
        for i in range(3):
            cube_axes_actor.GetTitleTextProperty(i).SetFontSize(font_size)
            cube_axes_actor.GetTitleTextProperty(i).SetColor(color)
            cube_axes_actor.GetTitleTextProperty(i).SetFontFamily(font_family)
            cube_axes_actor.GetTitleTextProperty(i).SetBold(bold)

            cube_axes_actor.GetLabelTextProperty(i).SetFontSize(font_size)
            cube_axes_actor.GetLabelTextProperty(i).SetColor(color)
            cube_axes_actor.GetLabelTextProperty(i).SetFontFamily(font_family)
            cube_axes_actor.GetLabelTextProperty(i).SetBold(bold)

        self.add_actor(cube_axes_actor, reset_camera=False, pickable=False)
        self.cube_axes_actor = cube_axes_actor

        if all_edges:
            self.add_bounding_box(color=color, corner_factor=corner_factor)

        if fmt is not None:
            cube_axes_actor.SetXLabelFormat(fmt)
            cube_axes_actor.SetYLabelFormat(fmt)
            cube_axes_actor.SetZLabelFormat(fmt)

        return cube_axes_actor

    def add_bounds_axes(self, *args, **kwargs):
        """Add bounds axes.

        DEPRECATED: Please use ``show_bounds`` or ``show_grid``.

        """
        logging.warning('`add_bounds_axes` is deprecated. Use `show_bounds` or `show_grid`.')
        return self.show_bounds(*args, **kwargs)

    def remove_bounding_box(self):
        """Remove bounding box."""
        if hasattr(self, '_box_object'):
            actor = self.bounding_box_actor
            self.bounding_box_actor = None
            del self._box_object
            self.remove_actor(actor, reset_camera=False)

    def add_bounding_box(self, color="grey", corner_factor=0.5, line_width=None,
                         opacity=1.0, render_lines_as_tubes=False,
                         lighting=None, reset_camera=None, outline=True,
                         culling='front', loc=None):
        """Add an unlabeled and unticked box at the boundaries of plot.

        Useful for when wanting to plot outer grids while still retaining all
        edges of the boundary.

        Parameters
        ----------
        corner_factor : float, optional
            If ``all_edges``, this is the factor along each axis to
            draw the default box. Dafuault is 0.5 to show the full
            box.

        corner_factor : float, optional
            This is the factor along each axis to draw the default
            box. Dafuault is 0.5 to show the full box.

        line_width : float, optional
            Thickness of lines.

        opacity : float, optional
            Opacity of mesh.  Should be between 0 and 1.  Default 1.0

        outline : bool
            Default is ``True``. when False, a box with faces is shown with
            the specified culling

        culling : str, optional
            Does not render faces that are culled. Options are ``'front'`` or
            ``'back'``. Default is ``'front'`` for bounding box.

        loc : int, tuple, or list
            Index of the renderer to add the actor to.  For example,
            ``loc=2`` or ``loc=(1, 1)``.  If None, selects the last
            active Renderer.

        """
        if lighting is None:
            lighting = rcParams['lighting']

        self.remove_bounding_box()
        if color is None:
            color = rcParams['outline_color']
        rgb_color = parse_color(color)
        if outline:
            self._bounding_box = vtk.vtkOutlineCornerSource()
            self._bounding_box.SetCornerFactor(corner_factor)
        else:
            self._bounding_box = vtk.vtkCubeSource()
        self._bounding_box.SetBounds(self.bounds)
        self._bounding_box.Update()
        self._box_object = wrap(self._bounding_box.GetOutput())
        name = 'BoundingBox({})'.format(hex(id(self._box_object)))

        mapper = vtk.vtkDataSetMapper()
        mapper.SetInputData(self._box_object)
        self.bounding_box_actor, prop = self.add_actor(mapper,
                                                       reset_camera=reset_camera,
                                                       name=name, culling=culling,
                                                       pickable=False)

        prop.SetColor(rgb_color)
        prop.SetOpacity(opacity)
        if render_lines_as_tubes:
            prop.SetRenderLinesAsTubes(render_lines_as_tubes)

        # lighting display style
        if lighting is False:
            prop.LightingOff()

        # set line thickness
        if line_width:
            prop.SetLineWidth(line_width)

        prop.SetRepresentationToSurface()

        return self.bounding_box_actor

    def remove_bounds_axes(self):
        """Remove bounds axes."""
        if hasattr(self, 'cube_axes_actor'):
            self.remove_actor(self.cube_axes_actor)

    @property
    def camera_position(self):
        """Return camera position of active render window."""
        return [scale_point(self.camera, self.camera.GetPosition(), invert=True),
                scale_point(self.camera, self.camera.GetFocalPoint(), invert=True),
                self.camera.GetViewUp()]

    def clear(self):
        """Remove all actors and properties."""
        if self._actors:
            for actor in list(self._actors):
                try:
                    self.remove_actor(actor, reset_camera=False)
                except KeyError:
                    pass

        self.RemoveAllViewProps()

    @camera_position.setter
    def camera_position(self, camera_location):
        """Set camera position of all active render windows."""
        if camera_location is None:
            return

        if isinstance(camera_location, str):
            camera_location = camera_location.lower()
            if camera_location == 'xy':
                self.view_xy()
            elif camera_location == 'xz':
                self.view_xz()
            elif camera_location == 'yz':
                self.view_yz()
            elif camera_location == 'yx':
                self.view_yx()
            elif camera_location == 'zx':
                self.view_zx()
            elif camera_location == 'zy':
                self.view_zy()
            return

        if isinstance(camera_location[0], (int, float)):
            return self.view_vector(camera_location)

        # everything is set explicitly
        self.camera.SetPosition(scale_point(self.camera, camera_location[0], invert=False))
        self.camera.SetFocalPoint(scale_point(self.camera, camera_location[1], invert=False))
        self.camera.SetViewUp(camera_location[2])

        # reset clipping range
        self.ResetCameraClippingRange()
        self.camera_set = True

    @property
    def camera(self):
        """Return the active camera for the rendering scene."""
        return self.GetActiveCamera()

    @camera.setter
    def camera(self, camera):
        """Set the active camera for the rendering scene."""
        self.SetActiveCamera(camera)
        self.camera_position = [
            scale_point(camera, camera.GetPosition(), invert=True),
            scale_point(camera, camera.GetFocalPoint(), invert=True),
            camera.GetViewUp()
        ]


    def set_focus(self, point):
        """Set focus to a point."""
        if isinstance(point, np.ndarray):
            if point.ndim != 1:
                point = point.ravel()
        self.camera.SetFocalPoint(scale_point(self.camera, point, invert=False))

    def set_position(self, point, reset=False):
        """Set camera position to a point."""
        if isinstance(point, np.ndarray):
            if point.ndim != 1:
                point = point.ravel()
        self.camera.SetPosition(scale_point(self.camera, point, invert=False))
        if reset:
            self.reset_camera()
        self.camera_set = True

    def set_viewup(self, vector):
        """Set camera viewup vector."""
        if isinstance(vector, np.ndarray):
            if vector.ndim != 1:
                vector = vector.ravel()
        self.camera.SetViewUp(vector)


    def enable_parallel_projection(self):
        """Enable parallel projection.

        The camera will have a parallel projection. Parallel projection is
        often useful when viewing images or 2D datasets.

        """
        self.camera.SetParallelProjection(True)


    def disable_parallel_projection(self):
        """Reset the camera to use perspective projection."""
        self.camera.SetParallelProjection(False)


    def remove_actor(self, actor, reset_camera=False):
        """Remove an actor from the Renderer.

        Parameters
        ----------
        actor : vtk.vtkActor
            Actor that has previously added to the Renderer.

        reset_camera : bool, optional
            Resets camera so all actors can be seen.

        Return
        ------
        success : bool
            True when actor removed.  False when actor has not been
            removed.

        """
        name = None
        if isinstance(actor, str):
            name = actor
            keys = list(self._actors.keys())
            names = []
            for k in keys:
                if k.startswith('{}-'.format(name)):
                    names.append(k)
            if len(names) > 0:
                self.remove_actor(names, reset_camera=reset_camera)
            try:
                actor = self._actors[name]
            except KeyError:
                # If actor of that name is not present then return success
                return False
        if isinstance(actor, collections.Iterable):
            success = False
            for a in actor:
                rv = self.remove_actor(a, reset_camera=reset_camera)
                if rv or success:
                    success = True
            return success
        if actor is None:
            return False

        # First remove this actor's mapper from _scalar_bar_mappers
        _remove_mapper_from_plotter(self.parent, actor, False)
        self.RemoveActor(actor)

        if name is None:
            for k, v in self._actors.items():
                if v == actor:
                    name = k
        self._actors.pop(name, None)
        self.update_bounds_axes()
        if reset_camera:
            self.reset_camera()
        elif not self.camera_set and reset_camera is None:
            self.reset_camera()
        else:
            self.parent._render()
        return True


    def set_scale(self, xscale=None, yscale=None, zscale=None, reset_camera=True):
        """Scale all the datasets in the scene.

        Scaling in performed independently on the X, Y and Z axis.
        A scale of zero is illegal and will be replaced with one.

        """
        if xscale is None:
            xscale = self.scale[0]
        if yscale is None:
            yscale = self.scale[1]
        if zscale is None:
            zscale = self.scale[2]
        self.scale = [xscale, yscale, zscale]

        # Update the camera's coordinate system
        transform = vtk.vtkTransform()
        transform.Scale(xscale, yscale, zscale)
        self.camera.SetModelTransformMatrix(transform.GetMatrix())
        self.parent._render()
        if reset_camera:
            self.update_bounds_axes()
            self.reset_camera()

    @property
    def bounds(self):
        """Return the bounds of all actors present in the rendering window."""
        the_bounds = np.array([np.inf, -np.inf, np.inf, -np.inf, np.inf, -np.inf])

        def _update_bounds(bounds):
            def update_axis(ax):
                if bounds[ax*2] < the_bounds[ax*2]:
                    the_bounds[ax*2] = bounds[ax*2]
                if bounds[ax*2+1] > the_bounds[ax*2+1]:
                    the_bounds[ax*2+1] = bounds[ax*2+1]
            for ax in range(3):
                update_axis(ax)
            return

        for actor in self._actors.values():
            if isinstance(actor, vtk.vtkCubeAxesActor):
                continue
            if (hasattr(actor, 'GetBounds') and actor.GetBounds() is not None
                 and id(actor) != id(self.bounding_box_actor)):
                _update_bounds(actor.GetBounds())

        if np.any(np.abs(the_bounds)):
            the_bounds[the_bounds == np.inf] = -1.0
            the_bounds[the_bounds == -np.inf] = 1.0

        return the_bounds.tolist()

    @property
    def center(self):
        """Return the center of the bounding box around all data present in the scene."""
        bounds = self.bounds
        x = (bounds[1] + bounds[0])/2
        y = (bounds[3] + bounds[2])/2
        z = (bounds[5] + bounds[4])/2
        return [x, y, z]

    def get_default_cam_pos(self, negative=False):
        """Return the default focal points and viewup.

        Uses ResetCamera to make a useful view.

        """
        focal_pt = self.center
        if any(np.isnan(focal_pt)):
            focal_pt = (0.0, 0.0, 0.0)
        position = np.array(rcParams['camera']['position']).astype(float)
        if negative:
            position *= -1
        position = position / np.array(self.scale).astype(float)
        cpos = [position + np.array(focal_pt),
                focal_pt, rcParams['camera']['viewup']]
        return cpos

    def update_bounds_axes(self):
        """Update the bounds axes of the render window."""
        if (hasattr(self, '_box_object') and self._box_object is not None
                and self.bounding_box_actor is not None):
            if not np.allclose(self._box_object.bounds, self.bounds):
                color = self.bounding_box_actor.GetProperty().GetColor()
                self.remove_bounding_box()
                self.add_bounding_box(color=color)
        if hasattr(self, 'cube_axes_actor'):
            self.cube_axes_actor.SetBounds(self.bounds)
            if not np.allclose(self.scale, [1.0, 1.0, 1.0]):
                self.cube_axes_actor.SetUse2DMode(True)
            else:
                self.cube_axes_actor.SetUse2DMode(False)

    def reset_camera(self):
        """Reset the camera of the active render window.

        The camera slides along the vector defined from camera position to focal point
        until all of the actors can be seen.

        """
        self.ResetCamera()
        self.parent._render()

    def isometric_view(self):
        """Reset the camera to a default isometric view.

        DEPRECATED: Please use ``view_isometric``.

        """
        return self.view_isometric()

    def view_isometric(self, negative=False):
        """Reset the camera to a default isometric view.

        The view will show all the actors in the scene.

        """
        self.camera_position = self.get_default_cam_pos(negative=negative)
        self.camera_set = False
        return self.reset_camera()

    def view_vector(self, vector, viewup=None):
        """Point the camera in the direction of the given vector."""
        focal_pt = self.center
        if viewup is None:
            viewup = rcParams['camera']['viewup']
        cpos = [vector + np.array(focal_pt),
                focal_pt, viewup]
        self.camera_position = cpos
        return self.reset_camera()

    def view_xy(self, negative=False):
        """View the XY plane."""
        vec = np.array([0,0,1])
        viewup = np.array([0,1,0])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)

    def view_yx(self, negative=False):
        """View the YX plane."""
        vec = np.array([0,0,-1])
        viewup = np.array([1,0,0])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)

    def view_xz(self, negative=False):
        """View the XZ plane."""
        vec = np.array([0,-1,0])
        viewup = np.array([0,0,1])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)

    def view_zx(self, negative=False):
        """View the ZX plane."""
        vec = np.array([0,1,0])
        viewup = np.array([1,0,0])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)

    def view_yz(self, negative=False):
        """View the YZ plane."""
        vec = np.array([1,0,0])
        viewup = np.array([0,0,1])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)


    def view_zy(self, negative=False):
        """View the ZY plane."""
        vec = np.array([-1,0,0])
        viewup = np.array([0,1,0])
        if negative:
            vec *= -1
        return self.view_vector(vec, viewup)

    def disable(self):
        """Disable this renderer's camera from being interactive."""
        return self.SetInteractive(0)

    def enable(self):
        """Enable this renderer's camera to be interactive."""
        return self.SetInteractive(1)

    def enable_eye_dome_lighting(self):
        """Enable eye dome lighting (EDL)."""
        if hasattr(self, 'edl_pass'):
            return self
        # create the basic VTK render steps
        basic_passes = vtk.vtkRenderStepsPass()
        # blur the resulting image
        # The blur delegates rendering the unblured image to the basic_passes
        self.edl_pass = vtk.vtkEDLShading()
        self.edl_pass.SetDelegatePass(basic_passes)

        # tell the renderer to use our render pass pipeline
        self.glrenderer = vtk.vtkOpenGLRenderer.SafeDownCast(self)
        self.glrenderer.SetPass(self.edl_pass)
        return self.glrenderer

    def disable_eye_dome_lighting(self):
        """Disable eye dome lighting (EDL)."""
        if not hasattr(self, 'edl_pass'):
            return
        self.SetPass(None)
        del self.edl_pass
        return


    def get_pick_position(self):
        """Get the pick position/area as x0, y0, x1, y1."""
        x0 = int(self.GetPickX1())
        x1 = int(self.GetPickX2())
        y0 = int(self.GetPickY1())
        y1 = int(self.GetPickY2())
        return x0, y0, x1, y1


    def deep_clean(self):
        """Clean the renderer of the memory."""
        if hasattr(self, 'cube_axes_actor'):
            del self.cube_axes_actor
        if hasattr(self, 'edl_pass'):
            del self.edl_pass
        if hasattr(self, '_box_object'):
            self.remove_bounding_box()

        self.RemoveAllViewProps()
        self._actors = None
        # remove reference to parent last
        self.parent = None
        return


    def __del__(self):
        """Delete the renderer."""
        self.deep_clean()


def _remove_mapper_from_plotter(plotter, actor, reset_camera):
    """Remove this actor's mapper from the given plotter's _scalar_bar_mappers."""
    try:
        mapper = actor.GetMapper()
    except AttributeError:
        return
    for name in list(plotter._scalar_bar_mappers.keys()):
        try:
            plotter._scalar_bar_mappers[name].remove(mapper)
        except ValueError:
            pass
        if len(plotter._scalar_bar_mappers[name]) < 1:
            slot = plotter._scalar_bar_slot_lookup.pop(name)
            plotter._scalar_bar_mappers.pop(name)
            plotter._scalar_bar_ranges.pop(name)
            plotter.remove_actor(plotter._scalar_bar_actors.pop(name), reset_camera=reset_camera)
            plotter._scalar_bar_slots.add(slot)
    return
