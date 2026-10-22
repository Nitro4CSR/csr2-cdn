#!/usr/bin/env python3
"""Offline structural probe of the user-supplied CSR2 special-ladder UnityFS bundle.

No network access, session material, or writing of proprietary decoded assets.
Requires lz4 (`pip install lz4`); prints only structural metadata and exact
small text markers that are relevant to locating a Prestige template.
"""
import struct
import lzma

MAX_BUNDLE = 32 * 1024 * 1024
MAX_DECOMPRESSED = 80 * 1024 * 1024


def cstring(blob, offset):
    end = blob.index(b'\x00', offset)
    return blob[offset:end].decode('utf8'), end + 1


def load_unityfs(blob):
    # The default CDN installation must not require the optional events extra.
    # LZ4 is imported only when a binary Prestige bundle is decoded.
    try:
        import lz4.block
    except ImportError:
        raise ValueError("LZ4 decoder unavailable; install csr2-cdn[events]") from None
    sig, p = cstring(blob, 0)
    if sig != 'UnityFS':
        raise ValueError('Not a UnityFS file')
    version = struct.unpack_from('>I', blob, p)[0]
    p += 4
    engine, p = cstring(blob, p)
    generator, p = cstring(blob, p)
    total, packed, unpacked, flags = struct.unpack_from('>QIII', blob, p)
    p += 20
    if total != len(blob) or packed > MAX_BUNDLE or unpacked > MAX_DECOMPRESSED:
        raise ValueError('Invalid bundle lengths')
    if flags & 0x80:
        raise ValueError('Block directory at end not supported by this focused probe')
    p = (p + 15) & ~15
    packed_blocks = blob[p:p + packed]
    algo = flags & 0x3f
    directory = (packed_blocks if algo == 0 else
                 lz4.block.decompress(packed_blocks, uncompressed_size=unpacked)
                 if algo in (2, 3) else None)
    if directory is None or len(directory) != unpacked:
        raise ValueError('Unknown block directory compression')
    cursor = 16
    number = struct.unpack_from('>I', directory, cursor)[0]
    cursor += 4
    if number > 10000:
        raise ValueError('Implausible block count')
    blocks = []
    for i in range(number):
        u, c, f = struct.unpack_from('>IIH', directory, cursor)
        blocks.append((u, c, f))
        cursor += 10
    n_nodes = struct.unpack_from('>I', directory, cursor)[0]
    cursor += 4
    if n_nodes > 1000:
        raise ValueError('Implausible node count')
    nodes = []
    for _ in range(n_nodes):
        offset, size, flags = struct.unpack_from('>QQI', directory, cursor)
        cursor += 20
        name, cursor = cstring(directory, cursor)
        nodes.append((offset, size, name))
    p = (p + packed + 15) & ~15
    content = bytearray()
    for u, c, f in blocks:
        chunk = blob[p:p + c]
        p += c
        kind = f & 0x3f
        if len(content) + u > MAX_DECOMPRESSED or u > MAX_DECOMPRESSED:
            raise ValueError('Decompressed limit exceeded')
        if kind == 0:
            result = chunk
        elif kind in (2, 3):
            result = lz4.block.decompress(chunk, uncompressed_size=u)
        elif kind == 1:
            # Observed Android ASTC Car*Library bundles use Unity LZMA blocks.
            # Unity stores a five-byte LZMA1 properties header, not the eight-byte
            # uncompressed size required by Python's FORMAT_ALONE reader.
            if len(chunk) < 6 or chunk[0] != 0x5d:
                raise ValueError('Unsupported Unity LZMA properties')
            dictionary = struct.unpack_from('<I', chunk, 1)[0]
            if not 4096 <= dictionary <= 8 * 1024 * 1024:
                raise ValueError('Unity LZMA dictionary exceeds limit')
            try:
                dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{
                    'id': lzma.FILTER_LZMA1, 'dict_size': dictionary,
                    'lc': 3, 'lp': 0, 'pb': 2,
                }])
                result = dec.decompress(chunk[5:], max_length=u + 1)
            except lzma.LZMAError:
                raise ValueError('Bad Unity LZMA block') from None
        else:
            result = None
        if result is None or len(result) != u:
            raise ValueError('Bad block data')
        content.extend(result)
        if len(content) > MAX_DECOMPRESSED:
            raise ValueError('Decompressed limit exceeded')
    decoded = []
    for offset, size, name in nodes:
        if offset + size > len(content):
            raise ValueError('Out-of-range node')
        decoded.append((name, bytes(content[offset:offset + size])))
    return engine, generator, version, decoded


def analyze(path):
    blob = path.read_bytes()
    if len(blob) > MAX_BUNDLE:
        raise ValueError('Bundle too large')
    engine, generator, version, nodes = load_unityfs(blob)
    out = {'source_sha256': hashlib.sha256(blob).hexdigest(),
           'compressed_bytes': len(blob), 'unityfs_version': version,
           'unity_engine': generator, 'nodes': []}
    for name, node in nodes:
        record = {'node': name, 'decompressed_node_bytes': len(node)}
        if name == 'CAB-assets_client_metadata_special_ladder_events_database':
            if len(node) < 2640:
                raise ValueError('Node truncated')
            data_offset = struct.unpack_from('>Q', node, 32)[0]
            if data_offset > len(node) - 8:
                raise ValueError('Invalid serialized data offset')
            text_name_len = struct.unpack_from('<I', node, data_offset)[0]
            if text_name_len > 256:
                raise ValueError('Invalid TextAsset name')
            text_name = node[data_offset + 4:data_offset + 4 + text_name_len].decode('utf8')
            aligned = (data_offset + 4 + text_name_len + 3) & ~3
            script_len = struct.unpack_from('<I', node, aligned)[0]
            script_start = aligned + 4
            script = node[script_start:script_start + script_len]
            if len(script) != script_len:
                raise ValueError('TextAsset payload incomplete')
            record.update(text_asset_name=text_name, script_length=script_len,
                          serialized_group_count=struct.unpack_from('<I', script, 0)[0],
                          script_is_json=script.lstrip().startswith((b'{', b'[')))
            markers = ('silver_prestige', 'Silver_Prestige', 'PRESTIGE_CHAMPIONSHIP_SILVER_LADDERS',
                       'TEXT_CUPS_DESC_PRESTIGE', 'TEXT_PRESTIGE_CUP_ENTRY_REQUIREMENTS',
                       'CustomSpecialLadder')
            record['markers'] = {}
            for label in markers:
                needle = label.encode()
                positions = []
                pos = 0
                while (pos := script.find(needle, pos)) >= 0:
                    positions.append(pos)
                    pos += len(needle)
                record['markers'][label] = {'count': len(positions), 'script_offsets': positions[:64]}
            # Nearby short labels without including raw full asset body
            record['prestige_context_markers'] = []
            for offset in record['markers']['silver_prestige']['script_offsets']:
                near = script[max(0, offset - 130):offset + 200]
                labels = [x for x in ('CustomSpecialLadder','PRESTIGE_CHAMPIONSHIP_SILVER_LADDERS',
                                       'TEXT_CUPS_DESC_PRESTIGE','TEXT_PRESTIGE_CUP_ENTRY_REQUIREMENTS')
                          if x.encode() in near]
                record['prestige_context_markers'].append({'script_offset': offset, 'labels_within_130_before_or_200_after': labels})
        out['nodes'].append(record)
    return out

