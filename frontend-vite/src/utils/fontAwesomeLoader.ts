/**
 * FontAwesome 图标懒加载清单（唯一来源，取代原 src/icons.ts 的全量注册）。
 *
 * 作用：<FontAwesomeIcon>（懒加载包装组件）首次遇到某个图标时，按需动态导入
 * 该图标并注册到 library，避免把全部 solid 图标打进首屏 vendor 包。
 *
 * 维护：新增图标名时在此追加一条 `'kebab-name': () => import('...faXxx')`；
 * FA5 旧名写进下方 aliasToCanonical。vite.config.ts 会从本文件提取子路径写入
 * optimizeDeps.include，务必保持 `import('@fortawesome/free-solid-svg-icons/faXxx')`
 * 这种单引号写法。
 */
import type { IconDefinition } from '@fortawesome/fontawesome-common-types'
import { library } from '@fortawesome/fontawesome-svg-core'

type Loader = () => Promise<IconDefinition>

const loaders: Record<string, Loader> = {
  'angle-left': () => import('@fortawesome/free-solid-svg-icons/faAngleLeft').then((m) => m.faAngleLeft),
  'angle-right': () => import('@fortawesome/free-solid-svg-icons/faAngleRight').then((m) => m.faAngleRight),
  'angles-left': () => import('@fortawesome/free-solid-svg-icons/faAnglesLeft').then((m) => m.faAnglesLeft),
  'angles-right': () => import('@fortawesome/free-solid-svg-icons/faAnglesRight').then((m) => m.faAnglesRight),
  'arrow-left': () => import('@fortawesome/free-solid-svg-icons/faArrowLeft').then((m) => m.faArrowLeft),
  'arrow-right': () => import('@fortawesome/free-solid-svg-icons/faArrowRight').then((m) => m.faArrowRight),
  'arrow-rotate-right': () => import('@fortawesome/free-solid-svg-icons/faArrowRotateRight').then((m) => m.faArrowRotateRight),
  'arrow-up-right-from-square': () => import('@fortawesome/free-solid-svg-icons/faArrowUpRightFromSquare').then((m) => m.faArrowUpRightFromSquare),
  'arrows-rotate': () => import('@fortawesome/free-solid-svg-icons/faArrowsRotate').then((m) => m.faArrowsRotate),
  'barcode': () => import('@fortawesome/free-solid-svg-icons/faBarcode').then((m) => m.faBarcode),
  'bars': () => import('@fortawesome/free-solid-svg-icons/faBars').then((m) => m.faBars),
  'bell': () => import('@fortawesome/free-solid-svg-icons/faBell').then((m) => m.faBell),
  'bell-slash': () => import('@fortawesome/free-solid-svg-icons/faBellSlash').then((m) => m.faBellSlash),
  'bolt': () => import('@fortawesome/free-solid-svg-icons/faBolt').then((m) => m.faBolt),
  'box': () => import('@fortawesome/free-solid-svg-icons/faBox').then((m) => m.faBox),
  'box-archive': () => import('@fortawesome/free-solid-svg-icons/faBoxArchive').then((m) => m.faBoxArchive),
  'box-open': () => import('@fortawesome/free-solid-svg-icons/faBoxOpen').then((m) => m.faBoxOpen),
  'boxes-stacked': () => import('@fortawesome/free-solid-svg-icons/faBoxesStacked').then((m) => m.faBoxesStacked),
  'building': () => import('@fortawesome/free-solid-svg-icons/faBuilding').then((m) => m.faBuilding),
  'calculator': () => import('@fortawesome/free-solid-svg-icons/faCalculator').then((m) => m.faCalculator),
  'calendar-check': () => import('@fortawesome/free-solid-svg-icons/faCalendarCheck').then((m) => m.faCalendarCheck),
  'calendar-days': () => import('@fortawesome/free-solid-svg-icons/faCalendarDays').then((m) => m.faCalendarDays),
  'cart-shopping': () => import('@fortawesome/free-solid-svg-icons/faCartShopping').then((m) => m.faCartShopping),
  'chart-area': () => import('@fortawesome/free-solid-svg-icons/faChartArea').then((m) => m.faChartArea),
  'chart-bar': () => import('@fortawesome/free-solid-svg-icons/faChartBar').then((m) => m.faChartBar),
  'chart-column': () => import('@fortawesome/free-solid-svg-icons/faChartColumn').then((m) => m.faChartColumn),
  'chart-line': () => import('@fortawesome/free-solid-svg-icons/faChartLine').then((m) => m.faChartLine),
  'chart-pie': () => import('@fortawesome/free-solid-svg-icons/faChartPie').then((m) => m.faChartPie),
  'check': () => import('@fortawesome/free-solid-svg-icons/faCheck').then((m) => m.faCheck),
  'check-double': () => import('@fortawesome/free-solid-svg-icons/faCheckDouble').then((m) => m.faCheckDouble),
  'chevron-down': () => import('@fortawesome/free-solid-svg-icons/faChevronDown').then((m) => m.faChevronDown),
  'chevron-left': () => import('@fortawesome/free-solid-svg-icons/faChevronLeft').then((m) => m.faChevronLeft),
  'chevron-right': () => import('@fortawesome/free-solid-svg-icons/faChevronRight').then((m) => m.faChevronRight),
  'chevron-up': () => import('@fortawesome/free-solid-svg-icons/faChevronUp').then((m) => m.faChevronUp),
  'circle': () => import('@fortawesome/free-solid-svg-icons/faCircle').then((m) => m.faCircle),
  'circle-check': () => import('@fortawesome/free-solid-svg-icons/faCircleCheck').then((m) => m.faCircleCheck),
  'circle-exclamation': () => import('@fortawesome/free-solid-svg-icons/faCircleExclamation').then((m) => m.faCircleExclamation),
  'circle-info': () => import('@fortawesome/free-solid-svg-icons/faCircleInfo').then((m) => m.faCircleInfo),
  'circle-minus': () => import('@fortawesome/free-solid-svg-icons/faCircleMinus').then((m) => m.faCircleMinus),
  'circle-notch': () => import('@fortawesome/free-solid-svg-icons/faCircleNotch').then((m) => m.faCircleNotch),
  'circle-plus': () => import('@fortawesome/free-solid-svg-icons/faCirclePlus').then((m) => m.faCirclePlus),
  'circle-question': () => import('@fortawesome/free-solid-svg-icons/faCircleQuestion').then((m) => m.faCircleQuestion),
  'circle-xmark': () => import('@fortawesome/free-solid-svg-icons/faCircleXmark').then((m) => m.faCircleXmark),
  'clipboard-check': () => import('@fortawesome/free-solid-svg-icons/faClipboardCheck').then((m) => m.faClipboardCheck),
  'clipboard-list': () => import('@fortawesome/free-solid-svg-icons/faClipboardList').then((m) => m.faClipboardList),
  'clock': () => import('@fortawesome/free-solid-svg-icons/faClock').then((m) => m.faClock),
  'clock-rotate-left': () => import('@fortawesome/free-solid-svg-icons/faClockRotateLeft').then((m) => m.faClockRotateLeft),
  'cloud': () => import('@fortawesome/free-solid-svg-icons/faCloud').then((m) => m.faCloud),
  'cloud-arrow-up': () => import('@fortawesome/free-solid-svg-icons/faCloudArrowUp').then((m) => m.faCloudArrowUp),
  'code-branch': () => import('@fortawesome/free-solid-svg-icons/faCodeBranch').then((m) => m.faCodeBranch),
  'code-compare': () => import('@fortawesome/free-solid-svg-icons/faCodeCompare').then((m) => m.faCodeCompare),
  'code-fork': () => import('@fortawesome/free-solid-svg-icons/faCodeFork').then((m) => m.faCodeFork),
  'comment': () => import('@fortawesome/free-solid-svg-icons/faComment').then((m) => m.faComment),
  'comment-dots': () => import('@fortawesome/free-solid-svg-icons/faCommentDots').then((m) => m.faCommentDots),
  'compress': () => import('@fortawesome/free-solid-svg-icons/faCompress').then((m) => m.faCompress),
  'copy': () => import('@fortawesome/free-solid-svg-icons/faCopy').then((m) => m.faCopy),
  'cube': () => import('@fortawesome/free-solid-svg-icons/faCube').then((m) => m.faCube),
  'cubes': () => import('@fortawesome/free-solid-svg-icons/faCubes').then((m) => m.faCubes),
  'database': () => import('@fortawesome/free-solid-svg-icons/faDatabase').then((m) => m.faDatabase),
  'download': () => import('@fortawesome/free-solid-svg-icons/faDownload').then((m) => m.faDownload),
  'envelope-open-text': () => import('@fortawesome/free-solid-svg-icons/faEnvelopeOpenText').then((m) => m.faEnvelopeOpenText),
  'eraser': () => import('@fortawesome/free-solid-svg-icons/faEraser').then((m) => m.faEraser),
  'exclamation': () => import('@fortawesome/free-solid-svg-icons/faExclamation').then((m) => m.faExclamation),
  'expand': () => import('@fortawesome/free-solid-svg-icons/faExpand').then((m) => m.faExpand),
  'eye': () => import('@fortawesome/free-solid-svg-icons/faEye').then((m) => m.faEye),
  'eye-slash': () => import('@fortawesome/free-solid-svg-icons/faEyeSlash').then((m) => m.faEyeSlash),
  'file': () => import('@fortawesome/free-solid-svg-icons/faFile').then((m) => m.faFile),
  'file-arrow-down': () => import('@fortawesome/free-solid-svg-icons/faFileArrowDown').then((m) => m.faFileArrowDown),
  'file-code': () => import('@fortawesome/free-solid-svg-icons/faFileCode').then((m) => m.faFileCode),
  'file-csv': () => import('@fortawesome/free-solid-svg-icons/faFileCsv').then((m) => m.faFileCsv),
  'file-excel': () => import('@fortawesome/free-solid-svg-icons/faFileExcel').then((m) => m.faFileExcel),
  'file-export': () => import('@fortawesome/free-solid-svg-icons/faFileExport').then((m) => m.faFileExport),
  'file-image': () => import('@fortawesome/free-solid-svg-icons/faFileImage').then((m) => m.faFileImage),
  'file-import': () => import('@fortawesome/free-solid-svg-icons/faFileImport').then((m) => m.faFileImport),
  'file-invoice': () => import('@fortawesome/free-solid-svg-icons/faFileInvoice').then((m) => m.faFileInvoice),
  'file-invoice-dollar': () => import('@fortawesome/free-solid-svg-icons/faFileInvoiceDollar').then((m) => m.faFileInvoiceDollar),
  'file-lines': () => import('@fortawesome/free-solid-svg-icons/faFileLines').then((m) => m.faFileLines),
  'file-pdf': () => import('@fortawesome/free-solid-svg-icons/faFilePdf').then((m) => m.faFilePdf),
  'file-zipper': () => import('@fortawesome/free-solid-svg-icons/faFileZipper').then((m) => m.faFileZipper),
  'filter': () => import('@fortawesome/free-solid-svg-icons/faFilter').then((m) => m.faFilter),
  'floppy-disk': () => import('@fortawesome/free-solid-svg-icons/faFloppyDisk').then((m) => m.faFloppyDisk),
  'folder': () => import('@fortawesome/free-solid-svg-icons/faFolder').then((m) => m.faFolder),
  'folder-open': () => import('@fortawesome/free-solid-svg-icons/faFolderOpen').then((m) => m.faFolderOpen),
  'folder-tree': () => import('@fortawesome/free-solid-svg-icons/faFolderTree').then((m) => m.faFolderTree),
  'gauge': () => import('@fortawesome/free-solid-svg-icons/faGauge').then((m) => m.faGauge),
  'gear': () => import('@fortawesome/free-solid-svg-icons/faGear').then((m) => m.faGear),
  'gears': () => import('@fortawesome/free-solid-svg-icons/faGears').then((m) => m.faGears),
  'globe': () => import('@fortawesome/free-solid-svg-icons/faGlobe').then((m) => m.faGlobe),
  'hand-point-left': () => import('@fortawesome/free-solid-svg-icons/faHandPointLeft').then((m) => m.faHandPointLeft),
  'hand-pointer': () => import('@fortawesome/free-solid-svg-icons/faHandPointer').then((m) => m.faHandPointer),
  'hand-sparkles': () => import('@fortawesome/free-solid-svg-icons/faHandSparkles').then((m) => m.faHandSparkles),
  'hashtag': () => import('@fortawesome/free-solid-svg-icons/faHashtag').then((m) => m.faHashtag),
  'hourglass-half': () => import('@fortawesome/free-solid-svg-icons/faHourglassHalf').then((m) => m.faHourglassHalf),
  'house': () => import('@fortawesome/free-solid-svg-icons/faHouse').then((m) => m.faHouse),
  'image': () => import('@fortawesome/free-solid-svg-icons/faImage').then((m) => m.faImage),
  'inbox': () => import('@fortawesome/free-solid-svg-icons/faInbox').then((m) => m.faInbox),
  'industry': () => import('@fortawesome/free-solid-svg-icons/faIndustry').then((m) => m.faIndustry),
  'info': () => import('@fortawesome/free-solid-svg-icons/faInfo').then((m) => m.faInfo),
  'keyboard': () => import('@fortawesome/free-solid-svg-icons/faKeyboard').then((m) => m.faKeyboard),
  'layer-group': () => import('@fortawesome/free-solid-svg-icons/faLayerGroup').then((m) => m.faLayerGroup),
  'link': () => import('@fortawesome/free-solid-svg-icons/faLink').then((m) => m.faLink),
  'list': () => import('@fortawesome/free-solid-svg-icons/faList').then((m) => m.faList),
  'list-check': () => import('@fortawesome/free-solid-svg-icons/faListCheck').then((m) => m.faListCheck),
  'list-ul': () => import('@fortawesome/free-solid-svg-icons/faListUl').then((m) => m.faListUl),
  'location-dot': () => import('@fortawesome/free-solid-svg-icons/faLocationDot').then((m) => m.faLocationDot),
  'lock': () => import('@fortawesome/free-solid-svg-icons/faLock').then((m) => m.faLock),
  'lock-open': () => import('@fortawesome/free-solid-svg-icons/faLockOpen').then((m) => m.faLockOpen),
  'magnifying-glass': () => import('@fortawesome/free-solid-svg-icons/faMagnifyingGlass').then((m) => m.faMagnifyingGlass),
  'magnifying-glass-minus': () => import('@fortawesome/free-solid-svg-icons/faMagnifyingGlassMinus').then((m) => m.faMagnifyingGlassMinus),
  'magnifying-glass-plus': () => import('@fortawesome/free-solid-svg-icons/faMagnifyingGlassPlus').then((m) => m.faMagnifyingGlassPlus),
  'minus': () => import('@fortawesome/free-solid-svg-icons/faMinus').then((m) => m.faMinus),
  'mobile-screen-button': () => import('@fortawesome/free-solid-svg-icons/faMobileScreenButton').then((m) => m.faMobileScreenButton),
  'network-wired': () => import('@fortawesome/free-solid-svg-icons/faNetworkWired').then((m) => m.faNetworkWired),
  'note-sticky': () => import('@fortawesome/free-solid-svg-icons/faNoteSticky').then((m) => m.faNoteSticky),
  'paper-plane': () => import('@fortawesome/free-solid-svg-icons/faPaperPlane').then((m) => m.faPaperPlane),
  'paperclip': () => import('@fortawesome/free-solid-svg-icons/faPaperclip').then((m) => m.faPaperclip),
  'paste': () => import('@fortawesome/free-solid-svg-icons/faPaste').then((m) => m.faPaste),
  'pen': () => import('@fortawesome/free-solid-svg-icons/faPen').then((m) => m.faPen),
  'pen-clip': () => import('@fortawesome/free-solid-svg-icons/faPenClip').then((m) => m.faPenClip),
  'pen-to-square': () => import('@fortawesome/free-solid-svg-icons/faPenToSquare').then((m) => m.faPenToSquare),
  'phone': () => import('@fortawesome/free-solid-svg-icons/faPhone').then((m) => m.faPhone),
  'plus': () => import('@fortawesome/free-solid-svg-icons/faPlus').then((m) => m.faPlus),
  'print': () => import('@fortawesome/free-solid-svg-icons/faPrint').then((m) => m.faPrint),
  'puzzle-piece': () => import('@fortawesome/free-solid-svg-icons/faPuzzlePiece').then((m) => m.faPuzzlePiece),
  'ranking-star': () => import('@fortawesome/free-solid-svg-icons/faRankingStar').then((m) => m.faRankingStar),
  'rectangle-list': () => import('@fortawesome/free-solid-svg-icons/faRectangleList').then((m) => m.faRectangleList),
  'right-from-bracket': () => import('@fortawesome/free-solid-svg-icons/faRightFromBracket').then((m) => m.faRightFromBracket),
  'right-to-bracket': () => import('@fortawesome/free-solid-svg-icons/faRightToBracket').then((m) => m.faRightToBracket),
  'rotate-left': () => import('@fortawesome/free-solid-svg-icons/faRotateLeft').then((m) => m.faRotateLeft),
  'rotate-right': () => import('@fortawesome/free-solid-svg-icons/faRotateRight').then((m) => m.faRotateRight),
  'route': () => import('@fortawesome/free-solid-svg-icons/faRoute').then((m) => m.faRoute),
  'scissors': () => import('@fortawesome/free-solid-svg-icons/faScissors').then((m) => m.faScissors),
  'scroll': () => import('@fortawesome/free-solid-svg-icons/faScroll').then((m) => m.faScroll),
  'server': () => import('@fortawesome/free-solid-svg-icons/faServer').then((m) => m.faServer),
  'shield-halved': () => import('@fortawesome/free-solid-svg-icons/faShieldHalved').then((m) => m.faShieldHalved),
  'shirt': () => import('@fortawesome/free-solid-svg-icons/faShirt').then((m) => m.faShirt),
  'sitemap': () => import('@fortawesome/free-solid-svg-icons/faSitemap').then((m) => m.faSitemap),
  'sliders': () => import('@fortawesome/free-solid-svg-icons/faSliders').then((m) => m.faSliders),
  'sort': () => import('@fortawesome/free-solid-svg-icons/faSort').then((m) => m.faSort),
  'sort-down': () => import('@fortawesome/free-solid-svg-icons/faSortDown').then((m) => m.faSortDown),
  'sort-up': () => import('@fortawesome/free-solid-svg-icons/faSortUp').then((m) => m.faSortUp),
  'spinner': () => import('@fortawesome/free-solid-svg-icons/faSpinner').then((m) => m.faSpinner),
  'square': () => import('@fortawesome/free-solid-svg-icons/faSquare').then((m) => m.faSquare),
  'square-check': () => import('@fortawesome/free-solid-svg-icons/faSquareCheck').then((m) => m.faSquareCheck),
  'stopwatch': () => import('@fortawesome/free-solid-svg-icons/faStopwatch').then((m) => m.faStopwatch),
  'store': () => import('@fortawesome/free-solid-svg-icons/faStore').then((m) => m.faStore),
  'suitcase': () => import('@fortawesome/free-solid-svg-icons/faSuitcase').then((m) => m.faSuitcase),
  'table': () => import('@fortawesome/free-solid-svg-icons/faTable').then((m) => m.faTable),
  'table-cells': () => import('@fortawesome/free-solid-svg-icons/faTableCells').then((m) => m.faTableCells),
  'table-cells-large': () => import('@fortawesome/free-solid-svg-icons/faTableCellsLarge').then((m) => m.faTableCellsLarge),
  'tag': () => import('@fortawesome/free-solid-svg-icons/faTag').then((m) => m.faTag),
  'tags': () => import('@fortawesome/free-solid-svg-icons/faTags').then((m) => m.faTags),
  'thumbtack': () => import('@fortawesome/free-solid-svg-icons/faThumbtack').then((m) => m.faThumbtack),
  'ticket': () => import('@fortawesome/free-solid-svg-icons/faTicket').then((m) => m.faTicket),
  'trash': () => import('@fortawesome/free-solid-svg-icons/faTrash').then((m) => m.faTrash),
  'trash-can': () => import('@fortawesome/free-solid-svg-icons/faTrashCan').then((m) => m.faTrashCan),
  'triangle-exclamation': () => import('@fortawesome/free-solid-svg-icons/faTriangleExclamation').then((m) => m.faTriangleExclamation),
  'truck': () => import('@fortawesome/free-solid-svg-icons/faTruck').then((m) => m.faTruck),
  'truck-fast': () => import('@fortawesome/free-solid-svg-icons/faTruckFast').then((m) => m.faTruckFast),
  'truck-ramp-box': () => import('@fortawesome/free-solid-svg-icons/faTruckRampBox').then((m) => m.faTruckRampBox),
  'upload': () => import('@fortawesome/free-solid-svg-icons/faUpload').then((m) => m.faUpload),
  'user': () => import('@fortawesome/free-solid-svg-icons/faUser').then((m) => m.faUser),
  'user-gear': () => import('@fortawesome/free-solid-svg-icons/faUserGear').then((m) => m.faUserGear),
  'user-plus': () => import('@fortawesome/free-solid-svg-icons/faUserPlus').then((m) => m.faUserPlus),
  'users': () => import('@fortawesome/free-solid-svg-icons/faUsers').then((m) => m.faUsers),
  'users-gear': () => import('@fortawesome/free-solid-svg-icons/faUsersGear').then((m) => m.faUsersGear),
  'van-shuttle': () => import('@fortawesome/free-solid-svg-icons/faVanShuttle').then((m) => m.faVanShuttle),
  'wand-magic': () => import('@fortawesome/free-solid-svg-icons/faWandMagic').then((m) => m.faWandMagic),
  'warehouse': () => import('@fortawesome/free-solid-svg-icons/faWarehouse').then((m) => m.faWarehouse),
  'weight-hanging': () => import('@fortawesome/free-solid-svg-icons/faWeightHanging').then((m) => m.faWeightHanging),
  'weight-scale': () => import('@fortawesome/free-solid-svg-icons/faWeightScale').then((m) => m.faWeightScale),
  'xmark': () => import('@fortawesome/free-solid-svg-icons/faXmark').then((m) => m.faXmark),
  'yen-sign': () => import('@fortawesome/free-solid-svg-icons/faYenSign').then((m) => m.faYenSign),
}

const aliasToCanonical: Record<string, string> = {
  'archive': 'box-archive',
  'boxes': 'boxes-stacked',
  'calendar-alt': 'calendar-days',
  'calendar-check': 'calendar-check',
  'check-circle': 'circle-check',
  'cloud-upload-alt': 'cloud-arrow-up',
  'code-branch': 'code-branch',
  'code-compare': 'code-compare',
  'code-fork': 'code-fork',
  'cog': 'gear',
  'cogs': 'gears',
  'comment-dots': 'comment-dots',
  'compress': 'compress',
  'edit': 'pen-to-square',
  'exclamation-circle': 'circle-exclamation',
  'exclamation-triangle': 'triangle-exclamation',
  'expand': 'expand',
  'file-archive': 'file-zipper',
  'file-code': 'file-code',
  'file-excel': 'file-excel',
  'file-export': 'file-export',
  'file-image': 'file-image',
  'file-import': 'file-import',
  'file-invoice': 'file-invoice',
  'file-invoice-dollar': 'file-invoice-dollar',
  'file-pdf': 'file-pdf',
  'hand-sparkles': 'hand-sparkles',
  'history': 'clock-rotate-left',
  'hourglass-half': 'hourglass-half',
  'info-circle': 'circle-info',
  'list-alt': 'rectangle-list',
  'list-tree': 'folder-tree',
  'magic': 'wand-magic',
  'magnifying-glass': 'magnifying-glass',
  'mobile-alt': 'mobile-screen-button',
  'network-wired': 'network-wired',
  'pen': 'pen',
  'pen-alt': 'pen-clip',
  'pencil-alt': 'pen-clip',
  'plus-circle': 'circle-plus',
  'question-circle': 'circle-question',
  'redo': 'arrow-rotate-right',
  'right-to-bracket': 'right-to-bracket',
  'rotate-left': 'rotate-left',
  'save': 'floppy-disk',
  'search': 'magnifying-glass',
  'search-minus': 'magnifying-glass-minus',
  'search-plus': 'magnifying-glass-plus',
  'shipping-fast': 'truck-fast',
  'shuttle-van': 'van-shuttle',
  'sitemap': 'sitemap',
  'sliders-h': 'sliders',
  'square': 'square',
  'sync-alt': 'arrows-rotate',
  'th-large': 'table-cells-large',
  'times': 'xmark',
  'times-circle': 'circle-xmark',
  'trash-alt': 'trash-can',
  'truck-loading': 'truck-ramp-box',
  'tshirt': 'shirt',
  'undo': 'rotate-left',
  'undo-alt': 'rotate-left',
  'user-cog': 'user-gear',
  'user-plus': 'user-plus',
  'users-cog': 'users-gear',
  'weight-hanging': 'weight-hanging',
}

const pending = new Map<string, Promise<IconDefinition>>()

export function canonicalIconName(name: string): string {
  return aliasToCanonical[name] ?? name
}

function exportIdFor(canonical: string): string {
  return (
    'fa' +
    canonical
      .split('-')
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join('')
  )
}

/**
 * dev 兜底：CJS 图标子路径可能尚未被 optimizeDeps 预构建（改配置后未重启 dev），
 * 此时回退到已预构建的包入口取同名导出。
 * 生产构建中 import.meta.env.DEV 为 false，该分支会被静态消除，不会打进产物。
 */
function fallbackFromIndex(id: string): Promise<IconDefinition> {
  return import('@fortawesome/free-solid-svg-icons').then((index) => {
    const def = (index as unknown as Record<string, IconDefinition | undefined>)[id]
    if (!def) throw new Error(`[fontAwesomeLoader] missing export: ${id}`)
    return def
  })
}

export function loadIcon(name: string): Promise<IconDefinition | null> {
  const canonical = canonicalIconName(name)
  const loader = loaders[canonical]
  if (!loader) return Promise.resolve(null)

  let p = pending.get(canonical)
  if (!p) {
    p = loader()
      .then((def) => {
        if (def) return def
        if (import.meta.env.DEV) return fallbackFromIndex(exportIdFor(canonical))
        throw new Error(`[fontAwesomeLoader] empty export for ${canonical}`)
      })
      .catch((err) => {
        if (!import.meta.env.DEV) throw err
        return fallbackFromIndex(exportIdFor(canonical))
      })
      .then((def) => {
        library.add(def)
        return def
      })
      .catch((loadError) => {
        pending.delete(canonical)
        throw loadError
      })
    pending.set(canonical, p)
  }
  return p
}
