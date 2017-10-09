import datetime
import os
import tempfile
import StringIO
import zipfile

import subprocess
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.generic.detail import View
from geonode.layers.views import _resolve_layer, _PERMISSION_MSG_VIEW


def clip_layer(request, layername):
    """Clipping raster layer and save to temp folder.
    Clipping layer by bbox or by geojson.
    :param layername: The layer name in Geonode.
    :type layername: basestring
    :return: file size
    """

    # PREPARATION
    layer = None
    raster_filepath = None
    extention = ''
    try:
        layer = _resolve_layer(
            request,
            layername,
            'base.view_resourcebase',
            _PERMISSION_MSG_VIEW)
    except Http404 as e:
        layername = layername.replace('geonode:', '')
        raster_filepath = os.path.join(settings.CLIPPED_DIRECTORY, '%s.geotiff' % layername)
        extention = 'geotiff'
        if not os.path.exists(raster_filepath):
            raise e

    query = request.GET or request.POST
    params = {
        param.upper(): value for param, value in query.iteritems()}
    bbox_string = params.get('BBOX', '')
    bboxArray = bbox_string.split(',')
    southwest_lat = bboxArray[1]
    bboxArray[1] = bboxArray[3]
    bboxArray[3] = southwest_lat

    bbox_string = ','.join(bboxArray)
    geojson = params.get('GEOJSON', '')
    current_date = datetime.datetime.today().strftime('%Y-%m-%d_%H-%M-%S')

    # create temp folder
    temporary_folder = os.path.join(
        tempfile.gettempdir(), 'clipped')
    try:
        os.mkdir(temporary_folder)
    except OSError as e:
        pass

    try:
        # get file for raster
        if not raster_filepath:
            file_names = []
            for layerfile in layer.upload_session.layerfile_set.all():
                file_names.append(layerfile.file.path)

            for target_file in file_names:
                if '.tif' in target_file:
                    raster_filepath = target_file
                    extention = 'tif'
                    break
    except AttributeError:
        raise Http404('Project can not be clipped or masked.')

    # get temp filename for output
    filename = os.path.basename(raster_filepath)
    clip_filename = filename + '.' + current_date + '.' + extention

    if bbox_string:
        output = os.path.join(
            temporary_folder,
            clip_filename
        )
        clipping = (
            'gdal_translate -projwin ' +
            '%(CLIP)s %(PROJECT)s %(OUTPUT)s'
        )
        request_process = clipping % {
            'CLIP': bbox_string.replace(',', ' '),
            'PROJECT': raster_filepath,
            'OUTPUT': output,
        }
    elif geojson:
        output = os.path.join(
            temporary_folder,
            clip_filename
        )
        mask_file = os.path.join(
            temporary_folder,
            filename + '.' + current_date + '.geojson'
        )
        _file = open(mask_file, 'w+')
        _file.write(geojson)
        _file.close()

        masking = ('gdalwarp -dstnodata 0 -q -cutline %(MASK)s ' +
                   '-crop_to_cutline ' +
                   '-dstalpha -of ' +
                   'GTiff %(PROJECT)s %(OUTPUT)s')
        request_process = masking % {
            'MASK': mask_file,
            'PROJECT': raster_filepath,
            'OUTPUT': output,
        }
    else:
        raise Http404('No bbox or geojson in parameters.')

    # generate if output is not created
    if not os.path.exists(output):
        if raster_filepath:
            subprocess.call(request_process, shell=True)

    if os.path.exists(output):
        # Check size
        max_clip_size = settings.MAXIMUM_CLIP_SIZE
        clipped_size = os.path.getsize(output)

        if float(clipped_size) > float(max_clip_size):
            max_clip_size_mb = int(max_clip_size) / 1000000
            response = JsonResponse({
                'error': 'Clipped file size is '
                         'bigger than ' + str(max_clip_size_mb) + ' mb'
            })
            response.status_code = 403
            return response

        response = JsonResponse({
            'success': 'Successfully clipping layer',
            'clip_filename': clip_filename
        })
        response.status_code = 200
        return response
    else:
        raise Http404('Project can not be clipped or masked.')


def download_clip(request, layername, clip_filename):
    """Download clipped file.
    Clipping layer by bbox or by geojson.
    :param layername: The layer name in Geonode.
    :type layername: basestring
    :param clip_filename: clipped filename
    :type clip_filename: basestring
    :return: The HTTPResponse with a file.
    """
    # PREPARATION
    layer = None
    extention = ''
    try:
        layer = _resolve_layer(
            request,
            layername,
            'base.view_resourcebase',
            _PERMISSION_MSG_VIEW)
    except Http404 as e:
        layername = layername.replace('geonode:', '')
        raster_filepath = os.path.join(settings.CLIPPED_DIRECTORY, '%s.geotiff' % layername)
        extention = 'geotiff'
        if not os.path.exists(raster_filepath):
            raise e

    query = request.GET or request.POST
    params = {
        param.upper(): value for param, value in query.iteritems()}
    current_date = datetime.datetime.today().strftime('%Y-%m-%d_%H-%M-%S')

    # create temp folder
    temporary_folder = os.path.join(
        tempfile.gettempdir(), 'clipped')
    try:
        os.mkdir(temporary_folder)
    except OSError as e:
        pass

    file_names = []
    if layer:
        for layerfile in layer.upload_session.layerfile_set.all():
            file_names.append(layerfile.file.path)

        for target_file in file_names:
            if '.tif' in target_file:
                target_filename, extention = os.path.splitext(target_file)
                break

    output = os.path.join(
        temporary_folder,
        clip_filename
    )

    if os.path.exists(output):
        # Create zip file
        s = StringIO.StringIO()
        zf = zipfile.ZipFile(s, "w")

        zip_subdir = layername + '_clipped'
        zip_filename = "%s.zip" % zip_subdir

        files_to_zipped = []
        for filename in file_names:
            if not filename.endswith('.qgs') and \
                    not filename.endswith(extention):
                files_to_zipped.append(filename)

        for fpath in files_to_zipped:
            # Calculate path for file in zip
            fdir, fname = os.path.split(fpath)
            fnames = fname.split('.')
            fname = fnames[0] + '.' + current_date + '.' + fnames[1]
            zip_path = os.path.join(zip_subdir, fname)
            zf.write(fpath, zip_path)

        # Add clipped raster
        opath, oname = os.path.split(output)
        zip_path = os.path.join(zip_subdir, oname)
        zf.write(output, zip_path)

        # Must close zip for all contents to be written
        zf.close()
        resp = HttpResponse(
            s.getvalue(), content_type="application/x-zip-compressed")
        resp['Content-Disposition'] = 'attachment; filename=%s' % zip_filename
        return resp
    else:
        raise Http404('Project can not be clipped or masked.')


class ClipVIew(View):
    template_name = 'clip-and-ship/clip-page.html'

    def get(self, request, geotiffname):
        context = {
            'geotiffname': geotiffname,
            'resource': {
                'get_tiles_url': "%sgwc/service/gmaps?layers=geonode:%s&zoom={z}&x={x}&y={y}&format=image/png8" % (
                    settings.GEOSERVER_PUBLIC_LOCATION,
                    geotiffname
                ),
                'service_typename': 'geonode:%s' % geotiffname
            }
        }
        return render(request, self.template_name, context)
