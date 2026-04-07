from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "es")
LOCALES_BY_LANGUAGE = {
    "en": "en-US",
    "es": "es-ES",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "toolbar.language": "Language",
        "toolbar.pages": "Pages",
        "nav.home": "Home",
        "language_name.en": "English",
        "language_name.es": "Spanish",
        "shared.words.and": "and",
        "shared.family.all": "All",
        "shared.family.all_families": "All families",
        "shared.family.opalescent": "Opalescent",
        "shared.family.transparent": "Transparent",
        "shared.family.tint": "Tint",
        "shared.mode.reflected": "Reflected",
        "shared.mode.transmitted": "Transmitted",
        "shared.element.selenium": "Selenium",
        "shared.element.sulfur": "Sulfur",
        "shared.element.copper": "Copper",
        "shared.element.lead": "Lead",
        "shared.element.silver": "Silver",
        "shared.element.gold": "Gold",
        "home.nav.mesh_crop": "Mesh Crop",
        "home.nav.glass_compare": "Glass Compare",
    },
    "es": {
        "toolbar.language": "Idioma",
        "language_name.en": "Ingles",
        "language_name.es": "Espanol",
        "shared.words.and": "y",
        "shared.family.all": "Todas",
        "shared.family.all_families": "Todas las familias",
        "shared.family.opalescent": "Opalescente",
        "shared.family.transparent": "Transparente",
        "shared.family.tint": "Tinte",
        "shared.mode.reflected": "Reflejada",
        "shared.mode.transmitted": "Transmitida",
        "shared.element.selenium": "Selenio",
        "shared.element.sulfur": "Azufre",
        "shared.element.copper": "Cobre",
        "shared.element.lead": "Plomo",
        "shared.element.silver": "Plata",
        "shared.element.gold": "Oro",
        "toolbar.pages": "Paginas",
        "nav.home": "Inicio",
        "home.title": "Kit y biblioteca de modelos y moldes de vidrio",
        "home.subtitle": "Usa los enlaces siguientes para abrir herramientas de modelos, diseno de moldes y exploracion de datos de vidrio.",
        "home.sections.model_tools": "Modelos y moldes",
        "home.sections.glass_library": "Biblioteca de vidrio",
        "home.sections.reference_sheets": "Hojas de referencia",
        "home.sections.svg_tools": "Herramientas SVG",
        "home.nav.cameo": "Generador de modelos Cameo",
        "home.nav.vessel": "Generador de modelos de vasija",
        "home.nav.tiles_panels": "Azulejos y paneles de modelo",
        "home.nav.mold_worksheet": "Hoja de trabajo del molde",
        "home.nav.mesh_crop": "Recorte de malla",
        "home.nav.glass_library": "Biblioteca de vidrio",
        "home.nav.glass_color_wheel": "Rueda de color del vidrio",
        "home.nav.glass_compare": "Comparar vidrio",
        "home.nav.layered_predictor": "Predictor de vidrio en capas",
        "home.nav.frit_mix_explorer": "Explorador de mezcla de frita",
        "home.nav.add_glass_sample": "Agregar muestra de vidrio",
        "home.nav.edit_glass_sample": "Editar muestra de vidrio",
        "home.nav.documentation": "Documentacion",
        "home.nav.opalescent_reference": "Referencia opalescente",
        "home.nav.transparent_reference": "Referencia transparente",
        "home.nav.tint_reference": "Referencia de tintes",
        "home.nav.svg_tiles": "Mosaicos SVG",
        "home.nav.svg_crop": "Recorte SVG",
        "page.cameo.title": "Generador de modelos de moldes cameo",
        "page.cameo.caption": "Los valores de escala de grises se convierten en un relieve digital esculpido y se invierten para formar un molde, de modo que la imagen cameo aparezca correctamente en el vidrio terminado. Los controles ajustan la profundidad, el respaldo y la resolucion de muestreo.",
        "page.cameo.controls": "Que hacen estos controles?",
        "page.cameo.controls.body": "- **Ancho objetivo (mm):** define el ancho final del modelo; la altura sigue la proporcion de la imagen.\n- **Maximo de relieve (mm):** define el rango del relieve desde **0.00 mm** hasta el maximo elegido.\n- **Espesor de respaldo (mm):** agrega una base plana estructural debajo del relieve.\n- **Invertir relieve:** invierte el mapeo tonal para que las zonas claras queden mas profundas (y viceversa). Dejalo activado para cameo.\n- **Resolucion:** dimension maxima de la imagen usada para el mapa de alturas; mas alto = mas detalle + mas lento.",
        "page.cameo.settings": "Configuracion",
        "page.cameo.actions.reset": "Restablecer configuracion",
        "page.cameo.fields.upload_image": "Cargar imagen",
        "page.cameo.fields.target_width": "Ancho objetivo del molde (mm)",
        "page.cameo.fields.relief_max": "Maximo de relieve de la imagen (mm)",
        "page.cameo.fields.base_backing": "Espesor de respaldo base (mm)",
        "page.cameo.fields.invert_relief": "Invertir relieve",
        "page.cameo.fields.resolution": "Resolucion",
        "page.cameo.caption.resolution": "Mas alto = mas detalle + mas lento. 600-900 suele ser un buen punto medio.",
        "page.cameo.messages.upload_first": "Carga una imagen para ver la previsualizacion del mapa de alturas invertido. La malla se genera solo cuando exportas.",
        "page.cameo.sections.input": "Entrada",
        "page.cameo.sections.preview": "Previsualizacion del mapa de alturas (invertido)",
        "page.cameo.sections.export": "Exportar",
        "page.cameo.messages.rebuild": "La configuracion cambio. Vuelve a generar la malla para actualizar la exportacion.",
        "page.cameo.actions.build": "Construir malla y habilitar descarga",
        "page.cameo.messages.building": "Construyendo malla...",
        "page.cameo.labels.output_size": "Tamano de salida",
        "page.cameo.labels.watertight": "Hermetica",
        "page.cameo.labels.total_volume": "Volumen total",
        "page.cameo.actions.download_zip": "Descargar ZIP (STL + configuracion)",
        "page.tiles_panels.title": "Generador de azulejos y paneles de modelo",
        "page.tiles.caption": "Carga una malla y cortala en paneles (tripitico por defecto) o en una cuadricula de mosaicos. El corte solo ocurre cuando haces clic en **Construir**.",
        "page.tiles.controls": "Que hacen estos controles?",
        "page.tiles.controls.body": "- **Paneles:** divide la malla en N paneles a lo largo de X o Y\n- **Mosaicos:** divide la malla en una cuadricula (`tiles_x x tiles_y`)\n- Exporta un ZIP con STL(s) + un archivo de configuracion\n- Opcional: incluye la malla original cargada en el ZIP\n",
        "page.tiles.settings": "Configuracion",
        "page.tiles.actions.reset": "Restablecer configuracion",
        "page.tiles.fields.upload_mesh": "Cargar malla",
        "page.tiles.fields.slice_mode": "Modo de corte",
        "page.tiles.mode.panels": "Paneles",
        "page.tiles.mode.tiles": "Mosaicos",
        "page.tiles.fields.split_axis": "Eje de corte - X | Vertical | Y | Horizontal",
        "page.tiles.fields.panel_sizing": "Tamano de paneles",
        "page.tiles.fields.equal_panels": "Paneles iguales",
        "page.tiles.fields.panel_widths_percent": "Anchos de panel (porcentaje)",
        "page.tiles.fields.panel_width_percents": "Porcentajes de ancho de panel (separados por comas)",
        "page.tiles.help.panel_width_percents": "Anchos que sumen 100. Ejemplo: 20,30,50 crea 3 paneles.",
        "page.tiles.errors.invalid_percents": "Porcentajes no validos: {error}",
        "page.tiles.fields.num_panels": "Numero de paneles",
        "page.tiles.fields.panel_gap": "Separacion entre paneles (mm)",
        "page.tiles.caption.panels_generated": "Paneles por generar: {count}",
        "page.tiles.validation.percent_positive": "todos los porcentajes deben ser mayores que 0",
        "page.tiles.validation.percent_sum": "los porcentajes deben sumar 100 (actual: {total:.3f})",
        "page.tiles.caption.tiles_grid": "Los mosaicos usan una cuadricula. El tamano de paneles se ignora en este modo.",
        "page.tiles.fields.tile_sizing_columns": "Tamano de columnas de mosaico (X - cortes verticales)",
        "page.tiles.fields.equal_tiles": "Mosaicos iguales",
        "page.tiles.fields.tile_widths_percent": "Anchos de mosaico (porcentaje)",
        "page.tiles.fields.tile_width_percents": "Porcentajes de ancho de mosaico (X - izquierda a derecha, separados por comas)",
        "page.tiles.help.tile_width_percents": "Anchos que sumen 100. Ejemplo: 60,40 crea 2 mosaicos a lo largo de X con reparto 60/40.",
        "page.tiles.errors.invalid_tile_x_percents": "Porcentajes de mosaico X no validos: {error}",
        "page.tiles.fields.tiles_x": "Mosaicos (X, izquierda a derecha)",
        "page.tiles.fields.tiles_y": "Filas de mosaicos (Y - cortes horizontales)",
        "page.tiles.fields.tile_gap": "Separacion entre mosaicos (mm)",
        "page.tiles.fields.overlap": "Solape (mm)",
        "page.tiles.fields.margin": "Margen desde los limites (mm)",
        "page.tiles.caption.tiles_generated": "Mosaicos por generar: {count}",
        "page.tiles.validation.tile_percent_positive": "todos los porcentajes de mosaico deben ser mayores que 0",
        "page.tiles.validation.tile_percent_sum": "los porcentajes de mosaico deben sumar 100 (actual: {total:.3f})",
        "page.tiles.fields.boolean_margin": "Margen de la caja booleana (mm)",
        "page.tiles.fields.boolean_engine": "Motor booleano",
        "page.tiles.help.boolean_engine": "Si el corte falla, prueba con 'auto' o instala un motor robusto (por ejemplo, manifold3d).",
        "page.tiles.fields.export_zip": "Exportar como ZIP (STLs + configuracion)",
        "page.tiles.fields.include_source": "Incluir la carga original en el ZIP",
        "page.tiles.internal.upload_not_mesh": "la carga no se pudo leer como una malla",
        "page.tiles.internal.mesh_empty": "la malla parece vacia",
        "page.tiles.internal.invalid_split_axis": "split_axis debe ser 'X' o 'Y'",
        "page.tiles.internal.zero_size_axis": "la malla no tiene tamano a lo largo del eje de corte elegido",
        "page.tiles.internal.panel_gap_too_large": "la separacion es demasiado grande para el tamano de la malla o la cantidad de paneles",
        "page.tiles.internal.positive_percent_required": "proporciona al menos un porcentaje positivo (por ejemplo, 40,60)",
        "page.tiles.internal.percent_list_zero": "la lista de porcentajes suma 0",
        "page.tiles.internal.invalid_panel_length": "longitud de panel no valida",
        "page.tiles.internal.margin_too_large": "el margen es demasiado grande; la region de mosaicos colapso",
        "page.tiles.internal.tile_x_percent_positive": "los porcentajes X de mosaico deben ser positivos",
        "page.tiles.internal.tile_x_percent_zero": "los porcentajes X de mosaico suman 0",
        "page.tiles.internal.tile_gap_x_too_large": "la separacion entre mosaicos es demasiado grande para el ancho de la malla o la cantidad de mosaicos",
        "page.tiles.internal.tiles_x_min": "los mosaicos en X deben ser >= 1",
        "page.tiles.internal.tiles_y_min": "las filas de mosaicos en Y deben ser >= 1",
        "page.tiles.internal.tile_gap_y_too_large": "la separacion entre mosaicos es demasiado grande para la altura de la malla o la cantidad de mosaicos",
        "page.tiles.internal.preview_percent_positive": "los anchos porcentuales deben ser mayores que 0",
        "page.tiles.internal.preview_percent_sum": "los anchos porcentuales deben sumar 100 (actual: {total:.3f})",
        "page.tiles.internal.preview_gap_too_large": "la separacion es demasiado grande para el tamano o la cantidad de paneles",
        "page.tiles.messages.fix_settings": "Corrige la configuracion anterior antes de construir.",
        "page.tiles.messages.upload_mesh": "Carga una malla para empezar.",
        "page.tiles.errors.load_mesh": "No se pudo cargar la malla: {error_type}: {error}",
        "page.tiles.messages.rebuild": "La configuracion cambio. Vuelve a construir para actualizar la exportacion.",
        "page.tiles.sections.preview": "Previsualizacion del corte",
        "page.tiles.messages.preview_unavailable": "Previsualizacion no disponible: {error_type}: {error}",
        "page.tiles.actions.build": "Construir cortes y habilitar descarga",
        "page.tiles.messages.building": "Cortando malla en paneles...",
        "page.tiles.actions.download_zip": "Descargar ZIP (STL + configuracion)",
        "page.vessel.title": "Generador de modelos de moldes de vasija",
        "page.vessel.caption": "Define el perfil de una vasija, carga una imagen de mapa de alturas y genera un STL imprimible envuelto.",
        "page.vessel.sections.profile": "Perfil",
        "page.vessel.fields.base_radius": "Radio de base (mm)",
        "page.vessel.fields.top_radius": "Radio superior (mm)",
        "page.vessel.fields.height": "Altura (mm)",
        "page.vessel.caption.midpoints": "Agrega puntos medios para curvar el perfil (opcional)",
        "page.vessel.fields.num_midpoints": "Numero de puntos medios",
        "page.vessel.fields.midpoint_height": "Punto medio {index} | altura (mm)",
        "page.vessel.fields.midpoint_radius": "Punto medio {index} | radio (mm)",
        "page.vessel.help.midpoint_height": "Distancia desde la base | 0 es abajo, {height} mm es arriba.",
        "page.vessel.sections.wall_relief": "Espesor de pared y relieve",
        "page.vessel.fields.wall_thickness": "Espesor de pared (mm)",
        "page.vessel.help.wall_thickness": "Espesor de la pared del molde detras del relieve cargado. Cambiar esto agrega estructura en el lado liso opuesto en lugar de mover la superficie con relieve.",
        "page.vessel.fields.relief": "Relieve (mm)",
        "page.vessel.help.relief": "Profundidad o altura del relieve envuelto con respecto al espesor de la pared.",
        "page.vessel.fields.placement": "Ubicacion del relieve",
        "page.vessel.placement.outside": "Exterior | relieve por fuera",
        "page.vessel.placement.inside": "Interior | tallado interior",
        "page.vessel.fields.invert_relief": "Invertir relieve",
        "page.vessel.help.invert_relief": "Intercambia picos y valles: las zonas oscuras quedan elevadas y las claras hundidas.",
        "page.vessel.sections.rim": "Borde",
        "page.vessel.fields.add_rim": "Agregar borde superior",
        "page.vessel.help.add_rim": "Recorta un canal de cuarto de circulo desde el radio superior limpio hacia el lado del relieve para dejar espacio para construir un borde.",
        "page.vessel.fields.rim_radius": "Radio del borde",
        "page.vessel.help.rim_radius": "Radio del corte de cuarto de circulo medido desde el borde superior limpio hacia el lado del relieve. Igualarlo al relieve reproduce la distribucion de 1/4 de circulo.",
        "page.vessel.fields.rim_smoothness": "Suavidad del borde",
        "page.vessel.help.rim_smoothness": "Segmentos de arco usados para redondear el canal del borde",
        "page.vessel.sections.heightmap": "Imagen de mapa de alturas",
        "page.vessel.fields.upload_image": "Cargar imagen (PNG, JPG, TIFF)",
        "page.vessel.caption.heightmap_preview": "Previsualizacion del mapa de alturas",
        "page.vessel.sections.resolution": "Resolucion",
        "page.vessel.caption.vertical_segments": "Los segmentos verticales escalan con la altura.",
        "page.vessel.fields.quality": "Calidad",
        "page.vessel.quality.draft": "Borrador (previsualizacion rapida)",
        "page.vessel.quality.standard": "Estandar",
        "page.vessel.quality.high": "Alta",
        "page.vessel.quality.ultra": "Ultra (detalle fino)",
        "page.vessel.caption.triangle_estimate": "-> {theta} angular x {vertical} vertical | ~{triangles}k triangulos",
        "page.vessel.fields.override_segments": "Sobrescribir segmentos manualmente",
        "page.vessel.fields.angular_segments": "Segmentos angulares",
        "page.vessel.help.angular_segments": "Segmentos alrededor de la circunferencia",
        "page.vessel.fields.vertical_spacing": "Espaciado vertical (mm por anillo)",
        "page.vessel.help.vertical_spacing": "Mas pequeno = mas anillos = detalle vertical mas fino",
        "page.vessel.actions.generate": "Generar",
        "page.vessel.actions.reset": "Restablecer valores",
        "page.vessel.messages.generating": "Generando malla...",
        "page.vessel.messages.mesh_ready": "Malla lista | {count} triangulos",
        "page.vessel.actions.download_stl": "Descargar STL",
        "page.vessel.actions.download_bundle": "Descargar paquete de construccion",
        "page.vessel.help.generate_first": "Haz clic en Generar primero",
        "page.vessel.help.generate_model_first": "Genera un modelo primero",
        "page.vessel.messages.bore_note": "Carga una imagen de mapa de alturas para calcular el volumen interno del vaciado tallado.",
        "page.vessel.metrics.output_height": "Altura de salida",
        "page.vessel.metrics.bore_volume": "Volumen interno del vaciado",
        "page.vessel.caption.bore_ml": "Equivale aproximadamente a {value} mL.",
        "page.vessel.messages.upload_heightmap_first": "Carga primero una imagen de mapa de alturas.",
        "page.vessel.messages.loading_heightmap": "Cargando mapa de alturas...",
        "page.vessel.messages.building_segments": "Construyendo malla ({theta}x{vertical} segmentos)...",
        "page.mesh_crop.title": "Recorte de malla",
        "page.mesh_crop.caption": "Carga STL | gira la imagen proxy | dibuja una caja de recorte | descarga.",
        "page.mesh_crop.messages.parse_ascii_fallback": "Problema al leer binario ({error}); intentando como ASCII...",
        "page.mesh_crop.fields.upload_stl": "Cargar STL",
        "page.mesh_crop.messages.parsing": "Analizando STL...",
        "page.mesh_crop.messages.rendering_proxy": "Renderizando vista proxy...",
        "page.mesh_crop.messages.file_loaded": "**{name}** | {triangles} triangulos",
        "page.mesh_crop.messages.upload_to_start": "Carga un STL para empezar.",
        "page.mesh_crop.sections.rotation": "Rotacion",
        "page.mesh_crop.fields.rotate_z": "Rotar Z grados",
        "page.mesh_crop.actions.apply_rotation": "Aplicar rotacion",
        "page.mesh_crop.messages.rerendering": "Volviendo a renderizar...",
        "page.mesh_crop.sections.crop": "Recorte",
        "page.mesh_crop.labels.selection_coords": "Seleccion (coordenadas de malla)",
        "page.mesh_crop.labels.selection_x": "X: {start} -> {end}",
        "page.mesh_crop.labels.selection_y": "Y: {start} -> {end}",
        "page.mesh_crop.metrics.triangles_in_crop": "Triangulos en el recorte",
        "page.mesh_crop.actions.download_cropped_stl": "Descargar STL recortado",
        "page.mesh_crop.messages.no_triangles": "No hay triangulos en la seleccion; prueba con una caja mas grande.",
        "page.mesh_crop.actions.clear_selection": "Borrar seleccion",
        "page.mesh_crop.caption.draw_box": "Dibuja una caja sobre la imagen para crear la seleccion de recorte.",
        "page.documentation.title": "Documentacion",
        "page.documentation.caption": "Materiales de referencia, especificaciones de materiales y notas de flujo de trabajo para el proceso de fabricacion de moldes 3D.",
        "page.documentation.materials": "Materiales",
        "page.documentation.workflows": "Flujos de trabajo",
        "page.documentation.tools_output": "Herramientas y resultados",
        "page.documentation.glossary": "Glosario",
        "page.documentation.safety": "Seguridad y manipulacion",
        "page.documentation.general_notes": "Notas generales",
        "page.reference.title": "Referencia de vidrio {family}",
        "page.reference.caption": "Transmitida (T) y reflejada (R) | Ordenada por numero de catalogo",
        "page.reference.return_label": "Referencia {family}",
        "page.reference.empty": "No se encontro vidrio {family} en la base de datos.",
        "page.reference.summary": "{count} vidrios | espesor de referencia {thickness} mm",
        "page.svg_tiles.title": "Mosaicos SVG",
        "page.svg_tiles.caption": "Carga | preprocesa con vpype | previsualiza la cuadricula | descarga mosaicos.",
        "page.svg_tiles.fields.upload_svg": "Cargar SVG",
        "page.svg_tiles.sections.vpype": "Preprocesamiento con vpype",
        "page.svg_tiles.messages.vpype_found": "vpype encontrado: {version}",
        "page.svg_tiles.messages.vpype_missing": "vpype no encontrado | instalalo con `pip install vpype`",
        "page.svg_tiles.fields.run_vpype": "Ejecutar vpype antes de mosaicar",
        "page.svg_tiles.fields.linemerge_tol": "linemerge --tolerance (mm)",
        "page.svg_tiles.help.linemerge_tol": "Une trazos cuyos extremos esten dentro de esta distancia. 0 = desactivado.",
        "page.svg_tiles.fields.min_length": "filter --min-length (mm)",
        "page.svg_tiles.help.min_length": "Elimina trazos mas cortos que este valor. 0 = desactivado.",
        "page.svg_tiles.fields.linesort": "linesort (minimizar recorrido de pluma)",
        "page.svg_tiles.sections.tiling": "Mosaicado",
        "page.svg_tiles.fields.rows": "Filas",
        "page.svg_tiles.fields.columns": "Columnas",
        "page.svg_tiles.sections.output": "Salida",
        "page.svg_tiles.fields.dpi": "DPI",
        "page.svg_tiles.fields.label_size": "Tamano de fuente de etiqueta (px)",
        "page.svg_tiles.fields.show_border": "Mostrar borde del mosaico",
        "page.svg_tiles.messages.upload_to_start": "Carga un SVG a la izquierda para empezar.",
        "page.svg_tiles.messages.running_vpype": "Ejecutando vpype...",
        "page.svg_tiles.sections.vpype_command": "Comando vpype",
        "page.svg_tiles.messages.vpype_completed": "vpype completado.",
        "page.svg_tiles.errors.vpype_failed": "vpype fallo:\n\n{error}",
        "page.svg_tiles.messages.vpype_skipped": "vpype esta activado pero todas las operaciones estan apagadas; se omite.",
        "page.svg_tiles.errors.parse_svg": "No se pudo interpretar el SVG: {error}",
        "page.svg_tiles.labels.source_canvas": "Lienzo fuente: {width:.0f} x {height:.0f} px | {inch_width:.3f}\" x {inch_height:.3f}\"",
        "page.svg_tiles.labels.tile_size": "Tamano de mosaico: {width:.0f} x {height:.0f} px | {inch_width:.3f}\" x {inch_height:.3f}\" | {count} mosaicos en total",
        "page.svg_tiles.sections.tile_map": "Mapa de mosaicos",
        "page.svg_tiles.actions.download_all": "Descargar los {count} mosaicos (.zip)",
        "page.svg_crop.title": "Recorte SVG",
        "page.svg_crop.caption": "Carga un SVG | define un rectangulo de recorte | previsualiza | opcionalmente ejecuta vpype | descarga.",
        "page.svg_crop.origin": "El origen (0, 0) esta en la esquina superior izquierda del lienzo SVG.",
        "page.svg_crop.tip": "Consejo: despues del recorte, usa la pagina de mosaicos SVG para dividir en mosaicos.",
        "page.svg_crop.reset_defaults": "Restablecer valores",
        "page.svg_crop.crop_region": "Region de recorte",
        "page.svg_crop.input_units": "Unidades de entrada",
        "page.svg_crop.fields.upload_svg": "Cargar SVG",
        "page.svg_crop.fields.x_offset": "Desplazamiento X",
        "page.svg_crop.fields.width": "Ancho",
        "page.svg_crop.fields.y_offset": "Desplazamiento Y",
        "page.svg_crop.fields.height": "Altura",
        "page.svg_crop.sections.vpype": "Postprocesamiento con vpype",
        "page.svg_crop.messages.vpype_found": "vpype encontrado: {version}",
        "page.svg_crop.messages.vpype_missing": "vpype no encontrado | instalalo con `pip install vpype`",
        "page.svg_crop.fields.run_vpype": "Ejecutar vpype despues del recorte",
        "page.svg_crop.fields.linemerge_tol": "linemerge --tolerance (mm)",
        "page.svg_crop.help.linemerge_tol": "Une trazos cuyos extremos esten dentro de esta distancia. 0 = desactivado.",
        "page.svg_crop.fields.min_length": "filter --min-length (mm)",
        "page.svg_crop.help.min_length": "Elimina trazos mas cortos que este valor. 0 = desactivado.",
        "page.svg_crop.fields.linesort": "linesort (minimizar recorrido de pluma)",
        "page.svg_crop.messages.upload_to_start": "Carga un SVG a la izquierda para empezar.",
        "page.svg_crop.errors.parse_svg": "No se pudo interpretar el SVG: {error}",
        "page.svg_crop.labels.source_canvas": "Lienzo fuente: {width:.2f} x {height:.2f} {unit}",
        "page.svg_crop.labels.crop_region": "Region de recorte: {width:.3f} x {height:.3f} {unit} en ({x:.3f}, {y:.3f}) {unit}",
        "page.svg_crop.sections.debug": "Depuracion de coordenadas SVG",
        "page.svg_crop.messages.running_vpype": "Ejecutando vpype...",
        "page.svg_crop.sections.vpype_command": "Comando vpype",
        "page.svg_crop.messages.vpype_completed": "vpype completado.",
        "page.svg_crop.errors.vpype_failed": "vpype fallo:\n\n{error}",
        "page.svg_crop.actions.download": "Descargar SVG recortado",
        "worksheet.title": "Hoja de trabajo del molde",
        "worksheet.caption": "Completa datos desde un settings.txt o ingresa valores manualmente. Selecciona el tipo de molde para ver sus calculos.",
        "worksheet.import.title": "Importar desde settings.txt",
        "worksheet.import.upload": "Suelta un settings.txt aqui",
        "worksheet.import.paste": "...o pega el contenido",
        "worksheet.import.parse": "Analizar y completar",
        "worksheet.import.prefilled": "Campos completados: {fields}",
        "worksheet.import.none_found": "No se encontraron campos reconocidos.",
        "worksheet.import.empty": "No hay contenido para analizar.",
        "worksheet.records.title": "Registros guardados",
        "worksheet.records.empty": "Aun no hay registros guardados.",
        "worksheet.records.saved_at": "Guardado {value}",
        "worksheet.records.no_date": "sin fecha",
        "worksheet.actions.load": "Cargar",
        "worksheet.actions.delete_help": "Eliminar",
        "worksheet.actions.new": "+ Nuevo",
        "worksheet.actions.reset": "Restablecer",
        "worksheet.actions.save": "Guardar",
        "worksheet.actions.update": "Actualizar",
        "worksheet.fields.title": "Titulo",
        "worksheet.fields.title_placeholder": "p. ej. Astrid #1",
        "worksheet.fields.date": "Fecha",
        "worksheet.sections.print_dimensions": "Dimensiones de la impresion 3D",
        "worksheet.sections.mold_geometry": "Geometria del molde",
        "worksheet.sections.mold_type": "Tipo de molde",
        "worksheet.sections.notes": "Notas",
        "worksheet.geometry.caption": "Ancho de separacion entre la impresion y las paredes de la caja de contencion.",
        "worksheet.fields.width": "Ancho X (mm)",
        "worksheet.fields.depth": "Profundidad Y (mm)",
        "worksheet.fields.base": "Base (mm)",
        "worksheet.fields.relief": "Relieve (mm)",
        "worksheet.fields.stl_volume": "Volumen STL (cm3)",
        "worksheet.fields.gap_width": "Ancho de separacion (mm)",
        "worksheet.fields.workflow": "Flujo del molde",
        "worksheet.mold.alginate_investment": "Alginato + revestimiento",
        "worksheet.mold.silicone": "Silicona",
        "worksheet.cards.print_calculations": "CALCULOS DE IMPRESION 3D",
        "worksheet.cards.mold_box": "CAJA DEL MOLDE",
        "worksheet.labels.base_volume": "Volumen de base",
        "worksheet.labels.max_z_height": "Altura maxima Z",
        "worksheet.labels.art_space_volume": "Volumen del espacio de arte",
        "worksheet.labels.actual_art_volume": "Volumen real del arte",
        "worksheet.labels.volume_to_max_z": "Volumen hasta Z maxima",
        "worksheet.labels.box_wd": "Caja A x P",
        "worksheet.labels.box_volume": "Volumen de la caja",
        "worksheet.labels.model_volume": "Volumen del modelo",
        "worksheet.labels.mold_volume": "Volumen del molde",
        "worksheet.alginate.title": "Alginato",
        "worksheet.investment.title": "Revestimiento",
        "worksheet.silicone.title": "Silicona",
        "worksheet.fields.adjust_base_z": "Ajustar base Z (mm)",
        "worksheet.fields.alginate_ratio": "Relacion de mezcla (agua : 1 alginato)",
        "worksheet.fields.alginate_ratio_help": "p. ej. 5.5 = 5.5 partes de agua por 1 de alginato",
        "worksheet.fields.silicone_ratio": "Relacion de mezcla (x : 1)",
        "worksheet.cards.alginate": "ACCU-CAST ALGINATE 570 PGV · {ratio} : 1",
        "worksheet.cards.dry_investment": "REVESTIMIENTO SECO / YESO + SILICE · Volumen del molde {volume} cm3",
        "worksheet.cards.rr910": "R&R 910 · Volumen del molde {volume} cm3 x 1.88",
        "worksheet.cards.silicone": "SIRATECH SILICONE · relacion {ratio} : 1",
        "worksheet.labels.mold_volume_box_model_z": "Volumen del molde (caja - modelo + Z)",
        "worksheet.labels.water": "Agua",
        "worksheet.labels.alginate": "Alginato",
        "worksheet.labels.mold_thickness": "Espesor del molde",
        "worksheet.labels.total_thickness": "Espesor total",
        "worksheet.labels.dry_investment": "Revestimiento seco",
        "worksheet.labels.plaster": "Yeso",
        "worksheet.labels.silica_flour": "Harina de silice",
        "worksheet.labels.rr910": "R&R 910",
        "worksheet.labels.total": "Total",
        "worksheet.labels.part_a": "Parte A",
        "worksheet.labels.part_b": "Parte B",
        "worksheet.fields.notes_placeholder": "Observaciones, ajustes o instrucciones especiales...",
        "errors.worksheet.title_required": "Ingresa un titulo antes de guardar.",
        "messages.worksheet.record_updated": "Registro actualizado: {title}",
        "messages.worksheet.record_saved": "Registro guardado: {title}",
        "editor.add.title": "Agregar muestra de vidrio",
        "editor.edit.title": "Editar datos del vidrio",
        "editor.fields.cat_id": "cat_id (6 digitos, p. ej. 001234)",
        "editor.fields.cat_id_placeholder": "001234",
        "editor.messages.normalized": "Normalizado a: **{cat_id}**",
        "editor.fields.color_name": "Nombre del color",
        "editor.fields.glass_family": "Familia de vidrio",
        "editor.warnings.families_missing": "La tabla glass_families no existe o esta vacia. La seleccion de familia se desactiva hasta que exista.",
        "editor.sections.elements": "Elementos contenidos (opcional)",
        "editor.sections.elements_caption": "Selecciona lo que contiene el vidrio. La app calcula automaticamente un resumen de 'puede reaccionar con'.",
        "editor.sections.reacts": "Puede reaccionar con (calculado)",
        "editor.fields.striker": "Striker",
        "editor.sections.cold": "Caracteristicas en frio (opcional)",
        "editor.sections.work": "Notas de trabajo (opcional)",
        "editor.placeholders.cold": "Ingresa las caracteristicas en frio...",
        "editor.placeholders.work": "Ingresa notas de trabajo...",
        "editor.sections.measurements": "Mediciones (reflejada / transmitida)",
        "editor.fields.thickness": "Espesor (mm)",
        "editor.tabs.transmitted": "Transmitida",
        "editor.tabs.reflected": "Reflejada",
        "editor.fields.red": "Rojo (R)",
        "editor.fields.green": "Verde (G)",
        "editor.fields.blue": "Azul (B)",
        "editor.fields.hue": "Tono (H)",
        "editor.fields.saturation": "Saturacion (S)",
        "editor.fields.brightness": "Brillo (B)",
        "editor.sections.images": "Imagenes (opcional)",
        "editor.images.caption_add": "Carga imagenes en resolucion completa (T y/o R). Los iconos se generan automaticamente (72x72 JPG) desde la imagen completa. Si no cargas nada, la biblioteca mostrara marcadores de posicion.",
        "editor.images.caption_edit": "Carga nuevas imagenes completas TIFF/JPG/PNG para transmitida (T) y/o reflejada (R). Los iconos se generan automaticamente (72x72 JPG) desde la imagen cargada. Si no cargas nada, se conservan las imagenes existentes.",
        "editor.images.full_t": "Imagen completa para transmitida (T) (TIFF/JPG/PNG)",
        "editor.images.full_r": "Imagen completa para reflejada (R) (TIFF/JPG/PNG)",
        "editor.images.preview_now": "Vista previa (lo que mostrara la biblioteca si guardas ahora)",
        "editor.images.icons": "Iconos",
        "editor.images.icon_t_short": "Icono (T)",
        "editor.images.icon_r_short": "Icono (R)",
        "editor.images.full_t_short": "Completa (T)",
        "editor.images.full_r_short": "Completa (R)",
        "editor.images.enter_cat_id": "Ingresa un cat_id para ver los nombres de destino y las vistas previas.",
        "editor.actions.save": "Guardar",
        "editor.actions.save_changes": "Guardar cambios",
        "editor.actions.cancel": "Cancelar",
        "editor.actions.upload_replacements": "Cargar reemplazos",
        "editor.search.label": "Buscar por cat_id o nombre del color",
        "editor.search.placeholder": "p. ej. 224 o Tomato Red",
        "editor.search.help": "Escribe un cat_id (224) o un nombre de color para buscar.",
        "editor.search.no_matches": "Sin coincidencias.",
        "editor.fields.select_record": "Seleccionar registro",
        "editor.fields.catalog": "Catalogo: {cat_id}",
        "editor.messages.saved": "Guardado.",
        "editor.messages.saved_with_id": "Guardado {cat_id}.",
        "editor.messages.saved_open_library": "Guardado {cat_id}. Abre {page} para revisarlo en la biblioteca.",
        "editor.messages.saved_files": "Archivos guardados:\n- {items}",
        "editor.messages.moved_files": "Archivos existentes movidos:\n- {items}",
        "editor.warnings.library_navigation_missing": "No se encontro la pagina de la biblioteca de vidrio en /pages. Navega desde la barra lateral.",
        "editor.warnings.library_navigation_failed": "No se pudo ir a la pagina de la biblioteca de vidrio. Usa la barra lateral.",
        "errors.editor.invalid_cat_id": "cat_id debe tener exactamente 6 digitos (p. ej. 001234).",
        "errors.editor.duplicate_cat_id": "cat_id {cat_id} ya existe en glass_catalog. Elige un id nuevo o edita el registro existente.",
        "errors.editor.save_failed": "Error al guardar: {error}",
        "errors.editor.db_missing": "Base de datos no encontrada: {path}",
        "errors.editor.no_families": "No se encontraron familias en la tabla glass_families.",
        "errors.editor.record_not_found": "No se encontro el registro en glass_catalog.",
        "errors.editor.sqlite": "Error de SQLite: {error}",
        "errors.editor.generic": "Error: {error}",
        "editor.danger.title": "Zona de peligro",
        "editor.danger.delete_record": "Eliminar registro",
        "editor.danger.confirm": "Escribe el cat_id para confirmar la eliminacion",
        "editor.danger.confirm_mismatch": "El texto de confirmacion no coincide con el cat_id.",
        "editor.danger.delete_button": "Eliminar registro",
        "messages.editor.deleted": "Se elimino {cat_id}.",
        "errors.editor.delete_failed": "Error al eliminar: {error}",
        "library.title": "Biblioteca de vidrio",
        "library.sidebar.title": "Explorar",
        "library.fields.preview_mode": "Modo de vista previa",
        "library.fields.sort_by": "Ordenar por",
        "library.fields.search": "Buscar (id o color)",
        "library.fields.striking_only": "Solo striker",
        "library.fields.interaction": "Interaccion",
        "library.fields.grid_columns": "Columnas de la cuadrilla",
        "library.actions.compare_selected": "Comparar seleccionados",
        "library.actions.clear_compare": "Limpiar comparacion",
        "library.messages.compare_set": "**Conjunto de comparacion:** {items}",
        "library.messages.compare_hint": "Selecciona 2-4 muestras para compararlas en una pagina dedicada.",
        "library.messages.empty": "No hay muestras de vidrio que coincidan con los filtros actuales.",
        "library.messages.pick_one": "Selecciona una muestra de vidrio para ver los detalles.",
        "library.messages.family_table_empty": "La tabla glass_families esta vacia.",
        "library.messages.open_datasheet_failed": "No se pudo abrir la pagina completa de la ficha tecnica.",
        "library.messages.compare_navigation_failed": "No se pudo abrir la pagina de comparacion.",
        "library.messages.no_measurement_mode": "No hay datos de medicion para este modo.",
        "library.messages.unnamed_sample": "Muestra sin nombre",
        "library.caption.summary": "{count} elementos ({family}, vista previa: {preview}, ordenado por: {sort})",
        "library.detail.open_datasheet": "Abrir ficha tecnica completa",
        "library.detail.compare": "Comparar",
        "color_wheel.title": "Rueda de color del vidrio",
        "color_wheel.sidebar.title": "Rueda de color",
        "color_wheel.fields.view": "Vista",
        "color_wheel.fields.mode": "Modo",
        "color_wheel.fields.harmony": "Superposicion armonica",
        "color_wheel.fields.search": "Buscar (id o color)",
        "color_wheel.fields.striking_only": "Solo striker",
        "color_wheel.view.2d": "Rueda 2D",
        "color_wheel.view.3d": "Rueda 3D",
        "color_wheel.harmony.none": "Ninguna",
        "color_wheel.harmony.complementary": "Complementaria",
        "color_wheel.harmony.analogous": "Analogica",
        "color_wheel.harmony.split_complementary": "Complementaria dividida",
        "color_wheel.harmony.triadic": "Triadica",
        "color_wheel.harmony.square": "Cuadrada",
        "color_wheel.axis.red": "Rojo",
        "color_wheel.axis.yellow": "Amarillo",
        "color_wheel.axis.green": "Verde",
        "color_wheel.axis.cyan": "Cian",
        "color_wheel.axis.blue": "Azul",
        "color_wheel.axis.magenta": "Magenta",
        "color_wheel.figure.harmony_targets": "Objetivos de armonia",
        "color_wheel.figure.harmony_matches": "Coincidencias de armonia",
        "color_wheel.figure.target_hue": "Tono objetivo",
        "color_wheel.figure.family": "Familia",
        "color_wheel.figure.harmony": "Armonia",
        "color_wheel.messages.empty": "No hay muestras de vidrio que coincidan con los filtros actuales.",
        "color_wheel.messages.select_point": "Selecciona un punto visible para inspeccionar una muestra.",
        "color_wheel.messages.no_harmony": "No hay objetivos de armonia disponibles para la seleccion actual.",
        "color_wheel.messages.open_datasheet_failed": "No se pudo abrir la pagina completa de la ficha tecnica.",
        "color_wheel.labels.family": "Familia: {family}",
        "color_wheel.labels.wheel_position": "Posicion en la rueda",
        "color_wheel.labels.harmony_overlay": "Superposicion armonica",
        "color_wheel.labels.measured_color": "Color medido",
        "color_wheel.caption.summary_2d": "{count} muestras en la rueda | angulo = H | radio = B | modo: {mode}",
        "color_wheel.caption.summary_3d": "{count} muestras en la rueda | angulo = H | radio = S | z = B | modo: {mode}",
        "color_wheel.caption.harmony": " | armonia: {harmony}",
        "color_wheel.position.mode": "Modo: {mode}",
        "color_wheel.position.hue": "H: {value} deg",
        "color_wheel.position.radius_s": "Radio (S): {value}",
        "color_wheel.position.radius_b": "Radio (B): {value}",
        "color_wheel.position.saturation_s": "S: {value}",
        "color_wheel.position.z_b": "Z (B): {value}",
        "color_wheel.position.brightness_b": "B: {value}",
        "color_wheel.caption.click_2d": "Haz clic en un punto para inspeccionar una muestra.",
        "color_wheel.caption.click_3d": "Haz clic en un punto para inspeccionar una muestra. Arrastra para orbitar la vista 3D.",
        "detail.title": "Detalle del vidrio",
        "detail.messages.no_glass_selected": "No se selecciono ningun vidrio. Abre esta pagina desde la biblioteca o la rueda de color con 'Abrir ficha tecnica completa'.",
        "detail.messages.not_found": "No se encontro ninguna entrada de catalogo para {glass_id}.",
        "detail.messages.return_failed": "No se pudo volver a la pagina anterior.",
        "detail.actions.download_pdf": "Descargar PDF",
        "detail.labels.contains": "Contiene:",
        "detail.labels.may_react_with": "Puede reaccionar con:",
        "detail.sections.reflected_light": "Luz reflejada",
        "detail.sections.transmitted_light": "Luz transmitida",
        "detail.sections.optical_curves": "Curvas de respuesta optica",
        "detail.sections.reflected": "Reflejada",
        "detail.sections.transmitted": "Transmitida",
        "detail.messages.no_reflected_data": "No hay datos de medicion reflejada.",
        "detail.messages.no_transmitted_data": "No hay datos de medicion transmitida.",
        "detail.messages.thickness_ref": "**Espesor (ref):** {thickness} mm",
        "detail.caption.optical_curves": "Extrapolacion de Beer-Lambert desde la medicion de referencia a {thickness} mm · Rango: 0 - {max_thickness} mm",
        "detail.table.color": "Color",
        "detail.table.brightness": "Brillo",
        "detail.table.saturation": "Saturacion",
        "detail.figure.ref_marker": "ref {thickness} mm",
        "detail.figure.channel_value": "Valor del canal (0-255)",
        "detail.figure.brightness_axis": "Brillo (0-100)",
        "detail.figure.color_shift.reflected": "Cambio de color reflejado",
        "detail.figure.color_shift.transmitted": "Cambio de color transmitido",
        "detail.figure.bs.reflected": "Brillo y saturacion reflejados",
        "detail.figure.bs.transmitted": "Brillo y saturacion transmitidos",
        "compare.title": "Comparar vidrios",
        "compare.actions.back_to_library": "<- Biblioteca de vidrio",
        "compare.actions.clear_set": "Limpiar conjunto de comparacion",
        "compare.actions.remove": "Quitar",
        "compare.messages.back_failed": "No se pudo volver a la biblioteca.",
        "compare.messages.select_from_library": "Selecciona 2-4 muestras en la biblioteca de vidrio y luego abre la pagina de comparacion.",
        "compare.messages.select_two": "Selecciona al menos dos muestras validas en la biblioteca de vidrio para compararlas.",
        "compare.messages.selected_count": "{count} muestras seleccionadas.",
        "compare.messages.open_datasheet_failed": "No se pudo abrir la pagina completa de la ficha tecnica.",
        "compare.sections.differences": "Diferencias",
        "compare.sections.plain_language": "Lectura en lenguaje claro",
        "compare.sections.quick_deltas": "Deltas rapidos",
        "compare.sections.reflected_overlay": "Superposicion reflejada",
        "compare.sections.transmitted_overlay": "Superposicion transmitida",
        "compare.messages.no_reflected_overlay": "No hay datos disponibles para la superposicion reflejada.",
        "compare.messages.no_transmitted_overlay": "No hay datos disponibles para la superposicion transmitida.",
        "compare.messages.no_measurement_mode": "No hay datos de medicion para este modo.",
        "compare.messages.no_optical_response": "No hay datos disponibles de respuesta optica.",
        "compare.messages.anchor_sample": "Muestra ancla para los resumentes de diferencias de abajo.",
        "compare.messages.reference_curves": "Muestra de referencia: {label}. Las curvas grises muestran la referencia y las curvas de color muestran el vidrio comparado.",
        "compare.badge.reference_sample": "Muestra de referencia",
        "compare.badge.close_match": "Coincidencia cercana",
        "compare.badge.striker": "Striker",
        "compare.badge.not_striker": "No striker",
        "compare.table.thickness": "Espesor",
        "compare.figure.channel_value": "Valor del canal",
        "compare.figure.color_shift_overlay_reflected": "Superposicion del cambio de color reflejado",
        "compare.figure.bs_overlay_reflected": "Superposicion de brillo y saturacion reflejados",
        "compare.figure.color_shift_overlay_transmitted": "Superposicion del cambio de color transmitido",
        "compare.figure.bs_overlay_transmitted": "Superposicion de brillo y saturacion transmitidos",
        "predictor.title": "Predictor de vidrio en capas",
        "predictor.sidebar.title": "Configuracion de capas",
        "predictor.fields.base_family": "Familia base",
        "predictor.fields.top_family": "Familia superior",
        "predictor.fields.base_glass": "Vidrio base",
        "predictor.fields.top_glass": "Vidrio superior",
        "predictor.fields.top_thickness": "Espesor superior (mm)",
        "predictor.caption.path_length": "Trayecto de ida y vuelta por el vidrio superior: {value} mm",
        "predictor.messages.missing_data": "Faltan el catalogo de vidrios o los datos de medicion.",
        "predictor.messages.no_family_matches": "No hay muestras de vidrio que coincidan con los filtros de familia actuales.",
        "predictor.messages.base_missing_reflected": "{label} no tiene datos de medicion reflejada.",
        "predictor.messages.top_missing_transmitted": "{label} no tiene datos de medicion transmitida.",
        "predictor.caption.intro": "Modelo inicial de apilado reflejado: el RGB reflejado de la base multiplicado por la transmision del vidrio superior en un doble paso a traves del espesor seleccionado.",
        "predictor.caption.reactive": "El potencial reactivo indica una posible interaccion quimica. El resultado visible aun depende de condiciones de coccion como temperatura, remojo, espesor y atmosfera del horno.",
        "predictor.sections.base": "Fuente reflejada de la base",
        "predictor.sections.top": "Filtro superior",
        "predictor.sections.result": "Resultado en capas previsto",
        "predictor.sections.model_notes": "Notas del modelo",
        "predictor.cards.base_caption": "Vidrio base usado como fuente del retorno reflejado.",
        "predictor.cards.top_caption": "Vidrio superior actuando como filtro de color.",
        "predictor.cards.result_caption": "Prediccion de doble paso sobre la base elegida.",
        "predictor.figure.rgb": "RGB reflejado previsto",
        "predictor.figure.hsb": "Brillo y saturacion previstos",
        "predictor.figure.thickness_axis": "Espesor superior (mm)",
        "predictor.figure.channel_value": "Valor del canal",
        "predictor.figure.zero_to_hundred": "0-100",
        "frit.title": "Explorador de mezcla de frita",
        "frit.sidebar.mix_setup": "Configuracion de la mezcla",
        "frit.sidebar.light_base": "Base clara",
        "frit.fields.reference_measurements": "Mediciones de referencia",
        "frit.fields.base_family": "Familia base",
        "frit.fields.base_glass": "Vidrio base",
        "frit.fields.mix_depth": "Profundidad de mezcla (mm)",
        "frit.fields.frit_size": "Tamano de frita",
        "frit.fields.grams": "{slot} gramos",
        "frit.messages.missing_data": "Faltan el catalogo de vidrios o los datos de medicion.",
        "frit.messages.no_base_matches": "No hay muestras de vidrio que coincidan con el filtro actual de familia base.",
        "frit.messages.base_missing_reflected": "{label} no tiene datos reflejados.",
        "frit.messages.no_slot_matches": "No hay muestras de vidrio que coincidan con el filtro actual para {slot}.",
        "frit.messages.slot_missing_mode": "{label} no tiene datos de {mode}.",
        "frit.messages.enter_grams": "Ingresa al menos algo de frita por peso para poder estimar la mezcla.",
        "frit.messages.layered_unavailable": "La vista en capas sobre la base no esta disponible para la mezcla actual porque faltan datos transmitidos para: {items}",
        "frit.caption.intro": "Heuristica inicial de frita: la lectura visible se estima como un promedio optico a traves de la profundidad, y el tamano de la frita afecta cuanta separacion local de color podria seguir visible.",
        "frit.sections.predicted_mix": "Lectura mezclada prevista",
        "frit.sections.layered_base": "En capas sobre base clara",
        "frit.sections.mixed_field": "Campo de frita mezclada",
        "frit.sections.predicted_layered": "Lectura en capas prevista",
        "frit.sections.model_notes": "Notas del modelo",
        "frit.cards.mix_caption": "Resultado con promedio optico en la profundidad seleccionada.",
        "frit.cards.layered_caption": "Esta seccion usa la mezcla seleccionada como filtro transmitido sobre la base clara elegida, con recorrido de ida y vuelta por el campo de frita.",
        "frit.figure.brightness": "Brillo a traves de la profundidad",
        "frit.figure.mixed_rgb": "RGB mezclado previsto a traves de la profundidad",
        "frit.figure.depth_axis": "Profundidad (mm)",
        "frit.figure.brightness_axis": "Brillo (B)",
        "frit.figure.channel_value": "Valor del canal",
        "editor.images.replace_full_t": "Reemplazar imagen completa - transmitida (T)",
        "editor.images.replace_full_r": "Reemplazar imagen completa - reflejada (R)",
        "editor.element.se": "Se (Selenio)",
        "editor.element.su": "S (Azufre)",
        "editor.element.cu": "Cu (Cobre)",
        "editor.element.pb": "Pb (Plomo)",
        "editor.element.ag": "Ag (Plata)",
        "editor.element.au": "Au (Oro)",
        "library.errors.catalog_load": "Error al cargar los datos del catalogo: {error}",
        "library.errors.measurement_load": "Error al cargar los datos de medicion: {error}",
        "library.errors.family_load": "Error al cargar los datos de familias: {error}",
        "color_wheel.target.complementary": "Complementaria",
        "color_wheel.target.analogous_minus": "Analogica -30",
        "color_wheel.target.analogous_plus": "Analogica +30",
        "color_wheel.target.split_minus": "Dividida -150",
        "color_wheel.target.split_plus": "Dividida +150",
        "color_wheel.target.triadic_plus": "Triadica +120",
        "color_wheel.target.triadic_minus": "Triadica -120",
        "color_wheel.target.square_90": "Cuadrada +90",
        "color_wheel.target.square_180": "Cuadrada +180",
        "color_wheel.target.square_270": "Cuadrada +270",
        "color_wheel.errors.load": "Error al cargar los datos de la rueda de color: {error}",
        "compare.notes.empty": "{title}: ninguno",
        "compare.summary.mode_read": "En {mode}, se ve {qualities} que la referencia.",
        "compare.summary.mode_hue": "Su tono en {mode} esta {hue_text}.",
        "compare.summary.hue_shift": "{qualifier}desplazado {degrees:.0f} deg",
        "compare.summary.reflected_light": "luz reflejada",
        "compare.summary.transmission": "transmision",
        "compare.summary.family_change": "Pertenece a la familia {compare_family} en lugar de {reference_family}.",
        "compare.summary.chemistry_adds": "agrega {items}",
        "compare.summary.chemistry_omits": "omite {items}",
        "compare.summary.chemistry": "Quimica: {details}.",
        "compare.summary.reactive_adds": "puede reaccionar con {items}",
        "compare.summary.reactive_less": "es menos propenso a reaccionar con {items}",
        "compare.summary.reactive": "Potencial reactivo: {details}.",
        "compare.summary.striker_yes": "Es striker, a diferencia de la referencia.",
        "compare.summary.striker_no": "No es striker, a diferencia de la referencia.",
        "compare.summary.close_to_reference": "Se ve muy cercano a la muestra de referencia en el resumen actual.",
        "compare.delta.no_reference": "{mode}: sin medicion de referencia",
        "compare.delta.no_measurement": "{mode}: sin medicion",
        "compare.delta.thickness": "{mode} espesor: {delta:+.2f} mm",
        "compare.delta.channel": "{mode} {label}: {delta:+.0f}",
        "compare.figure.ref_channel": "Ref {label}",
        "compare.figure.sample_channel": "Muestra {label}",
        "compare.figure.ref_brightness": "Brillo ref",
        "compare.figure.ref_saturation": "Saturacion ref",
        "compare.figure.sample_brightness": "Brillo muestra",
        "compare.figure.sample_saturation": "Saturacion muestra",
        "predictor.cards.base_subtitle": "Escaneo reflejado medido",
        "predictor.cards.base_note": "Esta es la luz que vuelve desde la base antes de que la capa superior la filtre.",
        "predictor.cards.top_subtitle": "Transmision modelada a {thickness:.2f} mm",
        "predictor.cards.top_note": "Espesor de referencia del escaneo transmitido: {thickness:.2f} mm.",
        "predictor.cards.result_title": "Resultado reflejado previsto",
        "predictor.cards.result_subtitle": "Recorrido de ida y vuelta por {thickness:.2f} mm de vidrio superior",
        "predictor.cards.result_note": "Esta es la estimacion inicial de lo que vuelve al ojo desde la pila en capas.",
        "predictor.summary.path_length": "Con {top_thickness:.2f} mm de vidrio superior, la luz recorre {path_length:.2f} mm de ida y vuelta por esa capa antes de regresar desde la base.",
        "predictor.summary.brighter": "mas brillante",
        "predictor.summary.darker": "mas oscura",
        "predictor.summary.more_saturated": "mas saturada",
        "predictor.summary.less_saturated": "menos saturada",
        "predictor.summary.compared_with_base": "Comparado con la base por si sola, el resultado en capas se ve {qualities}.",
        "predictor.summary.hue_shift": "El tono de la base cambia unos {degrees:.0f} deg cuando se agrega la capa superior.",
        "predictor.summary.darker_than_top": "Comparado con el vidrio superior sobre un fondo claro de escaneo, el resultado en capas vuelve mas oscuro porque la base limita la luz de retorno.",
        "predictor.summary.quieter_stack": "Es probable que esta pila se sienta notablemente mas apagada y amortiguada que la base sola.",
        "predictor.summary.reactive_yes": "Potencial reactivo: posible reaccion {pairings}.",
        "predictor.summary.reactive_no": "Potencial reactivo: no aparecio una combinacion reactiva evidente.",
        "predictor.notes.filter_model": "El vidrio superior se trata como un filtro transmitido con una atenuacion tipo Beer-Lambert.",
        "predictor.notes.double_pass": "El apilado reflejado usa un doble paso por la capa superior: una vez al bajar y otra al volver.",
        "predictor.notes.first_pass": "Es un predictor de primera pasada. Aun no modela perdidas de interfaz, dispersion por textura superficial ni microestructura formada en el horno.",
        "frit.cards.mix_title": "Resultado mezclado previsto",
        "frit.cards.mix_subtitle": "Lectura visual ponderada de {total:.2f} g en total",
        "frit.cards.mix_note": "Esto no es una mezcla fundida completa. Es una estimacion inicial de como podria verse el campo de frita mezclada. B ponderado = {weighted_b:.1f}.",
        "frit.cards.slot_caption": "{slot} en la profundidad seleccionada.",
        "frit.cards.slot_title": "Contribucion de {slot}",
        "frit.cards.slot_subtitle": "{grams:.2f} g en la mezcla",
        "frit.cards.note_default": "Modelado desde el modo de medicion seleccionado a la profundidad elegida.",
        "frit.cards.note_frit2": "Util para un segundo cuerpo de color o como ajuste, segun los gramos seleccionados.",
        "frit.cards.note_frit3": "Tercera frita opcional para mover el punto de oscurecimiento o ayudar a una mezcla dificil.",
        "frit.cards.note_zero": "Actualmente esta en 0.00 g, asi que esta lista para usarse sin cambiar la mezcla actual.",
        "frit.cards.base_caption": "Base clara usada como fuente del retorno reflejado.",
        "frit.cards.base_note": "Esta es la luz que vuelve desde la base antes de que el campo de frita la filtre.",
        "frit.cards.filter_caption": "La mezcla de frita seleccionada tratada como filtro superior.",
        "frit.cards.filter_title": "Filtro de frita mezclada",
        "frit.cards.filter_subtitle": "Transmision de ida por {depth:.2f} mm",
        "frit.cards.filter_note": "Esta es la lectura optica inicial del filtro del campo de frita mezclada antes del retorno reflejado desde la base.",
        "frit.cards.layered_result_caption": "Prediccion de ida y vuelta sobre la base elegida.",
        "frit.cards.layered_result_subtitle": "Recorrido de ida y vuelta por {depth:.2f} mm de profundidad de frita",
        "frit.cards.layered_result_note": "Esta es la estimacion inicial de lo que vuelve desde la base una vez que el campo de frita filtra la luz al bajar y al volver.",
        "frit.summary.layered.path": "Sobre {base_label}, el campo de frita se trata como un filtro transmitido con un recorrido de ida y vuelta de {path_length:.2f} mm por la mezcla.",
        "frit.summary.layered.compared_with_base": "Comparado con la base por si sola, la lectura en capas se ve {qualities}.",
        "frit.summary.layered.darker_than_filter": "Comparado con el campo de frita sobre su propio fondo claro de escaneo, el resultado en capas vuelve mas oscuro porque la base limita la luz de retorno.",
        "frit.summary.layered.first_pass": "Esta es una estimacion reflejada de primera pasada: la mezcla de frita se modela como un filtro sobre la base clara elegida en lugar de una mezcla fundida completa.",
        "frit.summary.mix.components": "Esta estimacion trata la mezcla como {components} a traves de {depth:.2f} mm de profundidad.",
        "frit.summary.mix.weighted_b": "Calculo de B ponderado: ({terms}) / {total:.2f} = {weighted_b:.1f}.",
        "frit.summary.mix.reference_compare": "Comparado con {slot} por si sola a esta profundidad, la lectura mezclada se ve {qualities}.",
        "frit.summary.mix.single_component": "Solo {slot} esta activa ahora mismo, asi que la lectura prevista coincide con esa frita.",
        "frit.summary.mix.dominant_strong": "{slot} esta haciendo la mayor parte del trabajo visual aqui, asi que el resultado deberia inclinarse con fuerza hacia esa familia de color.",
        "frit.summary.mix.dominant_moderate": "{slot} lidera la mezcla, pero las otras fritas aun deberian influir visiblemente en el resultado.",
        "frit.summary.mix.balanced": "Ninguna frita domina por completo, asi que el resultado deberia leerse como un campo mas equilibrado.",
        "frit.summary.mix.heuristic": "Esta pagina sigue siendo una heuristica: usa un promedio optico de la lectura visible en lugar de asumir que la frita se homogeneiza por completo durante la coccion.",
        "frit.figure.slot_brightness": "Brillo de {slot}",
        "frit.figure.mixed_brightness": "Brillo mezclado",
        "frit.notes.exploratory": "Esta pagina es exploratoria mas que prescriptiva. Da una estimacion amigable para estudio de la lectura visible.",
        "frit.notes.frit_size": "El tamano de la frita no cambia aqui el color promedio ponderado directamente; cambia la cantidad esperada de separacion local de color que aun podria verse.",
        "frit.notes.powdered": "El vidrio en polvo se trata aqui como la opcion que integra con mas suavidad, pero en la practica el aire atrapado y las burbujas aun deben resolverse antes de la coccion.",
        "frit.notes.homogenization": "La pagina no asume una homogeneizacion completa durante la coccion.",
        "frit.notes.brightness_chart": "La grafica de brillo esta aqui porque el brillo suele ser la senal de profundidad mas facil de usar cuando construyes una transicion a traves de un campo de frita mas grueso.",
        "frit.size.powdered": "Polvo",
        "frit.size.fine": "Fina",
        "frit.size.medium": "Media",
        "frit.size.coarse": "Gruesa",
        "frit.behaviour.powdered": "El vidrio en polvo deberia integrarse con mas suavidad, pero el control de burbujas importa mas antes de la coccion.",
        "frit.behaviour.fine": "La frita fina deberia integrarse con mas suavidad y promediarse visualmente mas rapido.",
        "frit.behaviour.medium": "La frita media conserva algo de contraste local pero aun se lee como un campo mezclado.",
        "frit.behaviour.coarse": "La frita gruesa tiene mas probabilidad de mantener visibles bolsillos de color individuales.",
        "frit.contrast.low": "Baja separacion local",
        "frit.contrast.medium": "Separacion local moderada",
        "frit.contrast.high": "Alta separacion local",
        "shared.actions.back": "Atras",
        "shared.sections.elements_present": "Elementos presentes",
        "shared.sections.reactive_potential": "Potencial reactivo",
        "shared.sections.cold_characteristics": "Caracteristicas en frio",
        "shared.sections.working_notes": "Notas de trabajo",
        "shared.interaction.contains": "Contiene",
        "shared.interaction.may_react_with": "Puede reaccionar con",
        "shared.sort.hue": "Tono (H)",
        "shared.sort.product_id": "ID de producto",
        "shared.sort.color_name": "Nombre del color",
        "shared.qualifier.slightly": "ligeramente ",
        "shared.qualifier.noticeably": "notablemente ",
    },
}

MONTH_NAMES = {
    "en": {
        "short": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "long": [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
    },
    "es": {
        "short": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
        "long": [
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ],
    },
}

FAMILY_NAME_KEYS = {
    "1": "shared.family.opalescent",
    "2": "shared.family.transparent",
    "3": "shared.family.tint",
    "opalescent": "shared.family.opalescent",
    "transparent": "shared.family.transparent",
    "tint": "shared.family.tint",
    "all": "shared.family.all",
    "all families": "shared.family.all_families",
}

MODE_NAME_KEYS = {
    "R": "shared.mode.reflected",
    "T": "shared.mode.transmitted",
    "reflected": "shared.mode.reflected",
    "transmitted": "shared.mode.transmitted",
}

ELEMENT_NAME_KEYS = {
    "se": "shared.element.selenium",
    "selenium": "shared.element.selenium",
    "su": "shared.element.sulfur",
    "sulfur": "shared.element.sulfur",
    "cu": "shared.element.copper",
    "copper": "shared.element.copper",
    "pb": "shared.element.lead",
    "lead": "shared.element.lead",
    "ag": "shared.element.silver",
    "silver": "shared.element.silver",
    "au": "shared.element.gold",
    "gold": "shared.element.gold",
}

NAVIGATION_SECTIONS = (
    ("", "", (("__entrypoint__", "nav.home", "Home"),)),
    (
        "home.sections.model_tools",
        "Model & Mold Tools",
        (
            ("pages/1_Cameo_Model_Generator.py", "home.nav.cameo", "Cameo Model Generator"),
            ("pages/4_Vessel_Model_Generator.py", "home.nav.vessel", "Vessel Model Generator"),
            ("pages/2_Model_Tiles_Panels.py", "home.nav.tiles_panels", "Model Tiles & Panels"),
            ("pages/3_Mold_Worksheet.py", "home.nav.mold_worksheet", "Mold Worksheet"),
            ("pages/5_Mesh_Crop.py", "home.nav.mesh_crop", "Mesh Crop"),
        ),
    ),
    (
        "home.sections.glass_library",
        "Glass Library",
        (
            ("pages/6_Glass_Library.py", "home.nav.glass_library", "Glass Library"),
            ("pages/7_Glass_Color_Wheel.py", "home.nav.glass_color_wheel", "Glass Color Wheel"),
            ("pages/15_Glass_Compare.py", "home.nav.glass_compare", "Glass Compare"),
            ("pages/16_Layered_Glass_Predictor.py", "home.nav.layered_predictor", "Layered Glass Predictor"),
            ("pages/17_Frit_Mix_Explorer.py", "home.nav.frit_mix_explorer", "Frit Mix Explorer"),
            ("pages/12_Add_Glass_Sample.py", "home.nav.add_glass_sample", "Add Glass Sample"),
            ("pages/13_Edit_Glass_Sample.py", "home.nav.edit_glass_sample", "Edit Glass Sample"),
        ),
    ),
    (
        "home.sections.reference_sheets",
        "Reference Sheets",
        (
            ("pages/14_Documentation.py", "home.nav.documentation", "Documentation"),
            ("pages/9_Opalescent_Reference.py", "home.nav.opalescent_reference", "Opalescent Reference"),
            ("pages/10_Transparent_Reference.py", "home.nav.transparent_reference", "Transparent Reference"),
            ("pages/11_Tint_Reference.py", "home.nav.tint_reference", "Tint Reference"),
        ),
    ),
    (
        "home.sections.svg_tools",
        "SVG Tools",
        (
            ("pages/20_SVG_Tiles.py", "home.nav.svg_tiles", "SVG Tiles"),
            ("pages/21_SVG_Crop.py", "home.nav.svg_crop", "SVG Crop"),
        ),
    ),
)


def ensure_i18n_state(default_language: str = DEFAULT_LANGUAGE) -> str:
    language = str(st.session_state.get("language", default_language) or default_language)
    if language not in SUPPORTED_LANGUAGES:
        language = default_language
    st.session_state["language"] = language
    st.session_state["locale"] = locale_for_language(language)
    return language


def current_language() -> str:
    return ensure_i18n_state()


def locale_for_language(language: str | None = None) -> str:
    lang = str(language or DEFAULT_LANGUAGE)
    return LOCALES_BY_LANGUAGE.get(lang, LOCALES_BY_LANGUAGE[DEFAULT_LANGUAGE])


def current_locale() -> str:
    ensure_i18n_state()
    return str(st.session_state["locale"])


def set_language(language: str) -> str:
    lang = str(language or DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    st.session_state["language"] = lang
    st.session_state["locale"] = locale_for_language(lang)
    return lang


def t(key: str, default: str | None = None, **params: Any) -> str:
    lang = current_language()
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(key, default if default is not None else key)
    try:
        return text.format(**params)
    except Exception:
        return text


def join_list(items: list[str]) -> str:
    parts = [str(item).strip() for item in items if str(item).strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" {t('shared.words.and', 'and')} " + parts[-1]


def translate_family_name(code: str | None = None, fallback_name: str | None = None) -> str:
    candidates = [str(code or "").strip(), str(fallback_name or "").strip().lower()]
    for candidate in candidates:
        if not candidate:
            continue
        key = FAMILY_NAME_KEYS.get(candidate if candidate in FAMILY_NAME_KEYS else candidate.lower())
        if key:
            return t(key, fallback_name or candidate)
    return str(fallback_name or code or "")


def translate_mode_name(mode: str | None) -> str:
    raw = str(mode or "").strip()
    key = MODE_NAME_KEYS.get(raw, MODE_NAME_KEYS.get(raw.lower()))
    return t(key, raw) if key else raw


def translate_element_name(element: str | None) -> str:
    raw = str(element or "").strip()
    key = ELEMENT_NAME_KEYS.get(raw, ELEMENT_NAME_KEYS.get(raw.lower()))
    return t(key, raw) if key else raw


def render_language_selector(*, use_sidebar: bool = True, key: str = "language_selector") -> str:
    ensure_i18n_state()
    target = st.sidebar if use_sidebar else st
    current = current_language()
    selected = target.selectbox(
        t("toolbar.language", "Language"),
        options=list(SUPPORTED_LANGUAGES),
        index=list(SUPPORTED_LANGUAGES).index(current),
        format_func=lambda code: t(f"language_name.{code}", code),
        key=key,
    )
    if selected != current:
        set_language(selected)
        st.rerun()
    return selected


def render_app_sidebar(*, nav_expanded: bool = False) -> str:
    ensure_i18n_state()
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    selected = render_language_selector(use_sidebar=True, key="sidebar_language_selector")
    st.sidebar.divider()
    ctx = get_script_run_ctx()
    entrypoint_page = Path(ctx.main_script_path).name if ctx and ctx.main_script_path else "Home.py"
    st.sidebar.page_link(entrypoint_page, label=t("nav.home", "Home"))
    with st.sidebar.expander(t("toolbar.pages", "Pages"), expanded=nav_expanded):
        for index, (section_key, section_default, links) in enumerate(NAVIGATION_SECTIONS[1:]):
            if section_key:
                st.markdown(f"**{t(section_key, section_default)}**")
            for page_path, label_key, label_default in links:
                if page_path == "__entrypoint__":
                    page_path = entrypoint_page
                st.page_link(page_path, label=t(label_key, label_default))
            if index < len(NAVIGATION_SECTIONS[1:]) - 1:
                st.divider()
    st.sidebar.divider()
    return selected


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, time):
        return datetime.combine(date.today(), value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        try:
            return datetime.combine(date.fromisoformat(text), time.min)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _coerce_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    dt_value = _coerce_datetime(value)
    return dt_value.time() if dt_value is not None else None


def format_date(value: Any, *, language: str | None = None, style: str = "medium") -> str:
    dt_value = _coerce_datetime(value)
    if dt_value is None:
        return ""

    lang = str(language or current_language())
    month_style = "long" if style == "long" else "short"
    month_name = MONTH_NAMES.get(lang, MONTH_NAMES[DEFAULT_LANGUAGE])[month_style][dt_value.month - 1]

    if style == "short":
        if lang == "es":
            return f"{dt_value.day:02d}/{dt_value.month:02d}/{dt_value.year:04d}"
        return f"{dt_value.month:02d}/{dt_value.day:02d}/{dt_value.year:04d}"

    if lang == "es":
        if style == "long":
            return f"{dt_value.day} de {month_name} de {dt_value.year}"
        return f"{dt_value.day} {month_name} {dt_value.year}"

    return f"{month_name} {dt_value.day}, {dt_value.year}"


def format_time(value: Any, *, language: str | None = None, style: str = "medium") -> str:
    time_value = _coerce_time(value)
    if time_value is None:
        return ""

    lang = str(language or current_language())
    include_seconds = style == "long"

    if lang == "es":
        return time_value.strftime("%H:%M:%S" if include_seconds else "%H:%M")

    hour = time_value.hour % 12 or 12
    suffix = "AM" if time_value.hour < 12 else "PM"
    if include_seconds:
        return f"{hour}:{time_value.minute:02d}:{time_value.second:02d} {suffix}"
    return f"{hour}:{time_value.minute:02d} {suffix}"


def format_datetime(value: Any, *, language: str | None = None, style: str = "medium") -> str:
    dt_value = _coerce_datetime(value)
    if dt_value is None:
        return ""

    lang = str(language or current_language())
    date_text = format_date(dt_value, language=lang, style=style)
    time_text = format_time(dt_value, language=lang, style=style)
    if not date_text:
        return time_text
    if not time_text:
        return date_text
    separator = " " if lang == "es" else ", "
    return f"{date_text}{separator}{time_text}"
