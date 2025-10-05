#!/usr/bin/env python3
"""
MPEG-TS Wrapper for KLV Data with PAT/PMT tables
Wraps KLV metadata into complete MPEG-TS stream for muxing with video
"""

import struct
import logging

logger = logging.getLogger(__name__)


class MPEGTSWrapper:
    """
    Complete MPEG-TS muxer for KLV data including PAT/PMT tables.
    
    Creates a minimal but valid MPEG-TS stream with:
    - PAT (Program Association Table) - PID 0x0000
    - PMT (Program Map Table) - PID 0x1000
    - KLV Data stream - PID 0x0100
    """
    
    TS_PACKET_SIZE = 188
    TS_SYNC_BYTE = 0x47
    
    # Standard PIDs
    PID_PAT = 0x0000
    PID_PMT = 0x1000
    PID_KLV = 0x0100
    
    # Program number
    PROGRAM_NUMBER = 1
    
    def __init__(self):
        """Initialize TS wrapper with continuity counters."""
        self.cc_pat = 0  # Continuity counter for PAT
        self.cc_pmt = 0  # Continuity counter for PMT
        self.cc_klv = 0  # Continuity counter for KLV data
        self.pat_sent = False
        self.pmt_sent = False
        self.packet_count = 0
    
    def wrap_klv(self, klv_data: bytes) -> bytes:
        """
        Wrap KLV data into MPEG-TS stream with PAT/PMT tables.
        
        Args:
            klv_data: Raw KLV binary data
            
        Returns:
            bytes: Complete TS stream (PAT + PMT + KLV data packets)
        """
        if not klv_data:
            return b""
        
        packets = []
        
        # Send PAT/PMT periodically (every ~1 second at 10 Hz = every 10 packets)
        if not self.pat_sent or self.packet_count % 10 == 0:
            packets.append(self._create_pat_packet())
            packets.append(self._create_pmt_packet())
            self.pat_sent = True
            self.pmt_sent = True
        
        # Create KLV data packets
        klv_packets = self._create_klv_packets(klv_data)
        packets.extend(klv_packets)
        
        self.packet_count += 1
        
        result = b''.join(packets)
        logger.debug(f"Created TS stream: {len(packets)} packets ({len(result)} bytes) for {len(klv_data)} bytes KLV")
        return result
    
    def _create_pat_packet(self) -> bytes:
        """Create PAT (Program Association Table) packet."""
        # PAT payload
        table_id = 0x00
        section_syntax = 1
        section_length = 13  # Fixed for single program
        
        # PAT section
        pat_data = struct.pack('>B', table_id)
        pat_data += struct.pack('>H', 
            (section_syntax << 15) | 
            (0 << 14) |  # reserved
            (3 << 12) |  # reserved
            section_length
        )
        pat_data += struct.pack('>H', 0x0001)  # Transport stream ID
        pat_data += struct.pack('>B',
            (3 << 6) |  # reserved
            (0 << 1) |  # version = 0
            1           # current_next = 1
        )
        pat_data += struct.pack('>B', 0)  # section_number
        pat_data += struct.pack('>B', 0)  # last_section_number
        
        # Program 1 -> PMT PID
        pat_data += struct.pack('>H', self.PROGRAM_NUMBER)
        pat_data += struct.pack('>H', 0xE000 | self.PID_PMT)
        
        # CRC32
        crc = self._calculate_crc32(pat_data)
        pat_data += struct.pack('>I', crc)
        
        # Build TS packet
        packet = self._build_ts_header(self.PID_PAT, True, self.cc_pat)
        packet += b'\x00'  # pointer_field
        packet += pat_data
        
        # Pad to 188 bytes
        packet += b'\xff' * (self.TS_PACKET_SIZE - len(packet))
        
        self.cc_pat = (self.cc_pat + 1) % 16
        return packet
    
    def _create_pmt_packet(self) -> bytes:
        """Create PMT (Program Map Table) packet for KLV data stream."""
        # PMT payload
        table_id = 0x02
        section_syntax = 1
        
        # Stream info for KLV (stream_type = 0x06 for private data)
        stream_type = 0x06  # Private PES packets
        elementary_pid = self.PID_KLV
        es_info_length = 0
        
        # Calculate section length (9 bytes header + 5 bytes per stream + 4 bytes CRC)
        section_length = 9 + 5 + 4
        
        # PMT section
        pmt_data = struct.pack('>B', table_id)
        pmt_data += struct.pack('>H',
            (section_syntax << 15) |
            (0 << 14) |  # reserved
            (3 << 12) |  # reserved
            section_length
        )
        pmt_data += struct.pack('>H', self.PROGRAM_NUMBER)
        pmt_data += struct.pack('>B',
            (3 << 6) |  # reserved
            (0 << 1) |  # version = 0
            1           # current_next = 1
        )
        pmt_data += struct.pack('>B', 0)  # section_number
        pmt_data += struct.pack('>B', 0)  # last_section_number
        pmt_data += struct.pack('>H', 0xE000 | 0x1FFF)  # PCR_PID (use null PID)
        pmt_data += struct.pack('>H', 0xF000)  # program_info_length = 0
        
        # Elementary stream info
        pmt_data += struct.pack('>B', stream_type)
        pmt_data += struct.pack('>H', 0xE000 | elementary_pid)
        pmt_data += struct.pack('>H', 0xF000 | es_info_length)
        
        # CRC32
        crc = self._calculate_crc32(pmt_data)
        pmt_data += struct.pack('>I', crc)
        
        # Build TS packet
        packet = self._build_ts_header(self.PID_PMT, True, self.cc_pmt)
        packet += b'\x00'  # pointer_field
        packet += pmt_data
        
        # Pad to 188 bytes
        packet += b'\xff' * (self.TS_PACKET_SIZE - len(packet))
        
        self.cc_pmt = (self.cc_pmt + 1) % 16
        return packet
    
    def _create_klv_packets(self, klv_data: bytes) -> list:
        """Create KLV data packets."""
        packets = []
        offset = 0
        data_length = len(klv_data)
        first_packet = True
        
        while offset < data_length:
            remaining = data_length - offset
            
            if first_packet:
                # First packet: add pointer field
                payload_capacity = self.TS_PACKET_SIZE - 5  # header(4) + pointer(1)
                chunk_size = min(remaining, payload_capacity)
                
                packet = self._build_ts_header(self.PID_KLV, True, self.cc_klv)
                packet += b'\x00'  # pointer_field
                packet += klv_data[offset:offset + chunk_size]
                
                first_packet = False
            else:
                # Continuation packets
                payload_capacity = self.TS_PACKET_SIZE - 4  # header only
                chunk_size = min(remaining, payload_capacity)
                
                packet = self._build_ts_header(self.PID_KLV, False, self.cc_klv)
                packet += klv_data[offset:offset + chunk_size]
            
            # Pad to 188 bytes
            packet += b'\xff' * (self.TS_PACKET_SIZE - len(packet))
            
            packets.append(packet)
            offset += chunk_size
            self.cc_klv = (self.cc_klv + 1) % 16
        
        return packets
    
    def _build_ts_header(self, pid: int, pusi: bool, cc: int) -> bytes:
        """Build 4-byte MPEG-TS header."""
        sync_byte = self.TS_SYNC_BYTE
        
        byte1 = ((1 if pusi else 0) << 6) | ((pid >> 8) & 0x1F)
        byte2 = pid & 0xFF
        byte3 = (0x01 << 4) | cc  # adaptation_field_control=01 (payload only), continuity_counter
        
        return struct.pack('BBBB', sync_byte, byte1, byte2, byte3)
    
    def _calculate_crc32(self, data: bytes) -> int:
        """Calculate CRC32 for MPEG-TS tables."""
        # MPEG-2 CRC32 polynomial
        crc = 0xFFFFFFFF
        
        for byte in data:
            crc ^= byte << 24
            for _ in range(8):
                if crc & 0x80000000:
                    crc = (crc << 1) ^ 0x04C11DB7
                else:
                    crc = crc << 1
                crc &= 0xFFFFFFFF
        
        return crc


def create_klv_ts_stream(klv_data: bytes, wrapper: MPEGTSWrapper = None) -> bytes:
    """
    Convenience function to wrap KLV data into TS stream.
    
    Args:
        klv_data: Raw KLV binary data
        wrapper: Optional existing MPEGTSWrapper instance
        
    Returns:
        bytes: Complete TS stream with PAT, PMT, and KLV data
    """
    if wrapper is None:
        wrapper = MPEGTSWrapper()
    
    return wrapper.wrap_klv(klv_data)
